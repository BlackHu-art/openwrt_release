#!/bin/sh

. $IPKG_INSTROOT/etc/init.d/shadowsocksr

ssrp_generate_dns() (
set -e
ssrp_filter() { grep "$@" || [ "$?" -eq 1 ]; }
check_run_environment

case "$USE_TABLES" in
	nftables)
		nft_support=1
		echolog "gfw2ipset: Using nftables"
		;;
	iptables)
		nft_support=0
		echolog "gfw2ipset: Using iptables"
		;;
	*)
		echolog "ERROR: No supported firewall backend detected"
		exit 1
		;;
esac

netflix() {
	local port="$1"
	if [ -f "$TMP_DNSMASQ_PATH/gfw_list.conf" ] && [ -s /etc/ssrplus/netflix.list ]; then
		ssrp_filter -vE '^\s*#|^\s*$' /etc/ssrplus/netflix.list > "$TMP_DNSMASQ_PATH/.netflix.list.clean"
		if [ -s "$TMP_DNSMASQ_PATH/.netflix.list.clean" ]; then
			ssrp_filter -v -F -f "$TMP_DNSMASQ_PATH/.netflix.list.clean" "$TMP_DNSMASQ_PATH/gfw_list.conf" > "$TMP_DNSMASQ_PATH/gfw_list.conf.tmp"
			mv "$TMP_DNSMASQ_PATH/gfw_list.conf.tmp" "$TMP_DNSMASQ_PATH/gfw_list.conf"
			if [ -f "$TMP_DNSMASQ_PATH/gfw_base.conf" ]; then
				ssrp_filter -v -F -f "$TMP_DNSMASQ_PATH/.netflix.list.clean" "$TMP_DNSMASQ_PATH/gfw_base.conf" > "$TMP_DNSMASQ_PATH/gfw_base.conf.tmp"
				mv "$TMP_DNSMASQ_PATH/gfw_base.conf.tmp" "$TMP_DNSMASQ_PATH/gfw_base.conf"
			fi
		fi
		rm -f "$TMP_DNSMASQ_PATH/.netflix.list.clean"
	fi
	if [ "$nft_support" = "1" ]; then
		# 移除 ipset
		sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1#$port\nnftset=\/&\/inet#ss_spec#netflix/" "/etc/ssrplus/netflix.list" >"$TMP_DNSMASQ_PATH/netflix_forward.conf"
	elif [ "$nft_support" = "0" ]; then
		sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1#$port\nipset=\/&\/netflix/" "/etc/ssrplus/netflix.list" >"$TMP_DNSMASQ_PATH/netflix_forward.conf"
	fi
}
mkdir -p $TMP_DNSMASQ_PATH

run_mode=$(uci_get_by_type global run_mode router)

if [ "$run_mode" = "oversea" ]; then
	cp -rf /etc/ssrplus/oversea_list.conf $TMP_DNSMASQ_PATH/
else
	cp -rf /etc/ssrplus/gfw_list.conf $TMP_DNSMASQ_PATH/
	cp -rf /etc/ssrplus/gfw_base.conf $TMP_DNSMASQ_PATH/
fi

for conf_file in gfw_base.conf gfw_list.conf oversea_list.conf; do
	conf="$TMP_DNSMASQ_PATH/$conf_file"
	[ -f "$conf" ] || continue

	if [ "$run_mode" = "gfw" ] || [ "$run_mode" = "oversea" ]; then
		if [ "$nft_support" = "1" ]; then
			# gfw + nft：ipset → nftset
			sed -i 's|ipset=/\([^/]*\)/\([^[:space:]]*\)|nftset=/\1/inet#ss_spec#\2|g' "$conf"
		fi
	else
		# 非 gfw：无条件清理所有分流引用
		# sed -i '/^[[:space:]]*\(ipset=\|nftset=\)/d' "$conf"
		sed -i '/^[[:space:]]*\(ipset=\|nftset=\)/d' "$conf"
	fi
done

if [ "$(uci_get_by_type global netflix_enable 0)" == "1" ]; then
	# 只有开启 NetFlix分流 才需要取值
	SHUNT_SERVER=$(uci_get_by_type global netflix_server nil)
else
	# 没有开启 设置为 nil
	SHUNT_SERVER=nil
fi
case "$SHUNT_SERVER" in
nil)
	rm -f $TMP_DNSMASQ_PATH/netflix_forward.conf
	;;
$(uci_get_by_type global global_server nil) | $switch_server | same)
	netflix $dns_port
	;;
*)
	netflix $tmp_shunt_dns_port
	;;
esac

# 此处使用 for 方式读取 防止 /etc/ssrplus/ 目录下的 black.list white.list deny.list 等2个或多个文件一行中存在空格 比如:# abc.com 而丢失：server
# Optimize: Batch filter using grep
for list_file in /etc/ssrplus/black.list /etc/ssrplus/white.list /etc/ssrplus/deny.list; do
	if [ -s "$list_file" ]; then
		ssrp_filter -vE '^\s*#|^\s*$' "$list_file" > "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean"
		if [ -s "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean" ]; then
			for target_file in "$TMP_DNSMASQ_PATH/gfw_list.conf" "$TMP_DNSMASQ_PATH/gfw_base.conf"; do
				if [ -f "$target_file" ]; then
					ssrp_filter -v -F -f "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean" "$target_file" > "${target_file}.tmp"
					mv "${target_file}.tmp" "$target_file"
				fi
			done
		fi
		rm -f "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean"
	fi
done

# 此处直接使用 cat 因为有 sed '/#/d' 删除了 数据
if [ "$nft_support" = "1" ]; then
	sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1#$dns_port\nnftset=\/&\/inet#ss_spec#blacklist/" "/etc/ssrplus/black.list" >"$TMP_DNSMASQ_PATH/blacklist_forward.conf"
	sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1\nnftset=\/&\/inet#ss_spec#whitelist/" "/etc/ssrplus/white.list" >"$TMP_DNSMASQ_PATH/whitelist_forward.conf"
elif [ "$nft_support" = "0" ]; then
	sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1#$dns_port\nipset=\/&\/blacklist/" "/etc/ssrplus/black.list" >"$TMP_DNSMASQ_PATH/blacklist_forward.conf"
	sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/server=\/&\/127.0.0.1\nipset=\/&\/whitelist/" "/etc/ssrplus/white.list" >"$TMP_DNSMASQ_PATH/whitelist_forward.conf"
fi
sed -e '/^$/d' -e '/#/d' -e "/.*/s/.*/address=\/&\//" "/etc/ssrplus/deny.list" >"$TMP_DNSMASQ_PATH/denylist.conf"

if [ "$(uci_get_by_type global adblock 0)" == "1" ]; then
	cp -f /etc/ssrplus/ad.conf $TMP_DNSMASQ_PATH/
	if [ -f "$TMP_DNSMASQ_PATH/ad.conf" ]; then
		for list_file in /etc/ssrplus/black.list /etc/ssrplus/white.list /etc/ssrplus/deny.list /etc/ssrplus/netflix.list; do
			if [ -s "$list_file" ]; then
				ssrp_filter -vE '^\s*#|^\s*$' "$list_file" > "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean"
				if [ -s "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean" ]; then
					ssrp_filter -v -F -f "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean" "$TMP_DNSMASQ_PATH/ad.conf" > "$TMP_DNSMASQ_PATH/ad.conf.tmp"
					mv "$TMP_DNSMASQ_PATH/ad.conf.tmp" "$TMP_DNSMASQ_PATH/ad.conf"
				fi
				rm -f "$TMP_DNSMASQ_PATH/.${list_file##*/}.clean"
			fi
		done
	fi
else
	rm -f $TMP_DNSMASQ_PATH/ad.conf
fi

)

if [ -n "${SSRP_DNS_STAGE:-}" ]; then
    case "$SSRP_DNS_STAGE" in
        "$DNSMASQ_CONF_DIR"/.ssrplus-dns.*) ;;
        *) exit 1 ;;
    esac
    TMP_DNSMASQ_PATH="$SSRP_DNS_STAGE"
    ssrp_generate_dns
else
    # A direct update must join the same locked, validated publication path.
    /etc/init.d/shadowsocksr reload
fi
