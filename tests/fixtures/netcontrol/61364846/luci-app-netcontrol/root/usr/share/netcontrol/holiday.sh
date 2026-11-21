# shellcheck shell=sh
#
# Copyright (C) 2026 rule2c <rule2c@gmail.com>
#
# 中国法定节假日判定，由 netcontrol 与 netcontrolctrl 共同 source。
#
# 数据格式（每行一天，只列与“周一至周五上班、周末休息”不同的日子）：
#     YYYY-MM-DD off|work 节日名
# off 是放假（含落在工作日的节假日），work 是调休补班（落在周末的上班日）。
#
# 查找顺序：用户自定义（uci holiday_extra）> 在线更新的年度文件 > 随包内置数据。
# 某一年三处都没有数据时，退回按周一至周五为工作日处理。

HOLIDAY_BUNDLED="/usr/share/netcontrol/holidays.txt"
HOLIDAY_DIR="/etc/netcontrol"
# 下一次允许自动在线更新的时刻（epoch）。/var 是 tmpfs，重启后会立即再试一次。
HOLIDAY_NEXT="/var/netcontrol.holiday_next"
HOLIDAY_URL_DEFAULT="https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"

# 某一天的类型。$1=YYYY-MM-DD，$2=该日的星期（1~7，date +%u）。
# 输出 "类型 来源"：类型为 work/off；来源为 custom/online/bundled/weekday。
# 来源为 weekday 说明这一年没有节假日数据。
holiday_day_type() {
    local day="$1" wd="$2" y e r f
    y="${day%%-*}"

    for e in $(uci -q get netcontrol.@netcontrol[0].holiday_extra 2>/dev/null); do
        case "$e" in
            "$day:off")  echo "off custom";  return ;;
            "$day:work") echo "work custom"; return ;;
        esac
    done

    # 在线文件按年存放，存在即代表这一年以它为准；否则用随包数据里这一年的部分
    f="$HOLIDAY_DIR/holiday-$y.txt"
    if [ -s "$f" ]; then
        r="online"
    else
        f="$HOLIDAY_BUNDLED"; r="bundled"
    fi
    e="$(awk -v d="$day" -v p="$y-" '
        index($1, p) == 1 { c = 1 }
        $1 == d && ($2 == "off" || $2 == "work") { t = $2 }
        END { print (t != "" ? t : (c ? "plain" : "none")) }' "$f" 2>/dev/null)"
    case "$e" in
        off|work) echo "$e $r"; return ;;
        plain)    [ "$wd" -le 5 ] && echo "work $r" || echo "off $r"; return ;;
    esac
    [ "$wd" -le 5 ] && echo "work weekday" || echo "off weekday"
}

# 已有数据的年份（在线 + 内置，去重升序）
holiday_years() {
    {
        for f in "$HOLIDAY_DIR"/holiday-*.txt; do
            [ -s "$f" ] || continue
            f="${f##*/holiday-}"; echo "${f%.txt}"
        done
        awk '$1 ~ /^[0-9][0-9][0-9][0-9]-/ { print substr($1, 1, 4) }' "$HOLIDAY_BUNDLED" 2>/dev/null
    } | sort -u | tr '\n' ' ' | sed 's/ $//'
}

# 下载到文件。OpenWrt 自带 uclient-fetch；wget 往往是它的软链，curl 需另装。
_holiday_fetch() {
    local url="$1" out="$2"
    if command -v uclient-fetch >/dev/null 2>&1; then
        uclient-fetch -q -T 20 -O "$out" "$url" 2>/dev/null
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL -m 20 -o "$out" "$url" 2>/dev/null
    elif command -v wget >/dev/null 2>&1; then
        wget -q -T 20 -O "$out" "$url" 2>/dev/null
    else
        return 1
    fi
}

# holiday-cn 的 JSON → 本地行格式。不依赖 jsonfilter：把空白全去掉后按 "}" 切成
# 一条条 day 对象，逐条抠 date / isOffDay / name。节日名里没有空白，去掉无妨。
# $1=JSON 文件 $2=年份。JSON 里的 year 与请求的年份不符时不输出任何内容。
_holiday_json_to_txt() {
    tr -d ' \t\r\n' < "$1" | awk -v y="$2" '
        BEGIN { RS = "}" }
        {
            if (index($0, "\"year\":" y ",") || index($0, "\"year\":" y "}")) ok = 1
            d = ""; o = ""; n = "-"
            if (match($0, /"date":"[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"/))
                d = substr($0, RSTART + 8, 10)
            if (match($0, /"isOffDay":true/))  o = "off"
            if (match($0, /"isOffDay":false/)) o = "work"
            if (match($0, /"name":"[^"]*"/))   n = substr($0, RSTART + 8, RLENGTH - 9)
            if (d != "" && o != "" && substr(d, 1, 4) == y) out[++k] = d " " o " " n
        }
        END { if (ok) for (i = 1; i <= k; i++) print out[i] }'
}

# 在线更新今年和明年的数据。明年的通知一般 11 月前后才发，取不到属正常。
# 返回 0 表示今年的数据已就绪（新下载或本来就有）；HOLIDAY_FETCHED=1 表示今年的
# 数据这次确实在线取到了，调用方据此决定多久后再试。
holiday_update() {
    local url y yy tmp txt ok=1 got=""
    HOLIDAY_FETCHED=0
    url="$(uci -q get netcontrol.@netcontrol[0].holiday_url 2>/dev/null)"
    url="${url:-$HOLIDAY_URL_DEFAULT}"
    y="$(date +%Y)"
    mkdir -p "$HOLIDAY_DIR" || return 1
    for yy in "$y" $((y + 1)); do
        tmp="/tmp/netcontrol-holiday.$$.json"
        txt="/tmp/netcontrol-holiday.$$.txt"
        rm -f "$tmp" "$txt"
        if _holiday_fetch "$(printf '%s' "$url" | sed "s/{year}/$yy/g")" "$tmp" \
            && _holiday_json_to_txt "$tmp" "$yy" > "$txt" && [ -s "$txt" ]; then
            # 内容没变就不写：/etc 在闪存上。先拷到同目录再 mv，守护进程不会读到半个文件
            cmp -s "$txt" "$HOLIDAY_DIR/holiday-$yy.txt" 2>/dev/null || {
                cp "$txt" "$HOLIDAY_DIR/.holiday-$yy.$$" && \
                    mv "$HOLIDAY_DIR/.holiday-$yy.$$" "$HOLIDAY_DIR/holiday-$yy.txt"
                rm -f "$HOLIDAY_DIR/.holiday-$yy.$$"
            }
            got="$got $yy"
            [ "$yy" = "$y" ] && { ok=0; HOLIDAY_FETCHED=1; }
        fi
        rm -f "$tmp" "$txt"
    done
    # 今年没取到，但本地已有今年的数据（在线旧文件或内置），也算就绪
    if [ "$ok" -ne 0 ]; then
        [ -s "$HOLIDAY_DIR/holiday-$y.txt" ] && ok=0
        grep -q "^$y-" "$HOLIDAY_BUNDLED" 2>/dev/null && ok=0
    fi
    HOLIDAY_GOT="${got# }"
    return "$ok"
}
