# Test-only UCI boundary for executing actual theme initialization scripts.
# Config/option/list input and output use real UCI file syntax. This does not
# emulate package lifecycle or theme migration decisions.
test_uci_parse() {
    local path=$1 line kind key value section='' index=0
    declare -gA TU_TYPES=() TU_VALUES=() TU_LISTS=()
    declare -ga TU_ORDER=()
    [[ -f "$path" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}
        read -r kind key value <<< "$line"
        case "$kind" in
            config)
                if [[ ${value:0:1} == "'" || ${value:0:1} == '"' ]]; then value=${value:1:${#value}-2}; fi
                section=${value:-cfg$index}; index=$((index + 1))
                TU_ORDER+=("$section"); TU_TYPES[$section]=$key
                ;;
            option|list)
                [[ -n "$section" ]] || return 1
                if [[ ${value:0:1} == "'" || ${value:0:1} == '"' ]]; then value=${value:1:${#value}-2}; fi
                if [[ $kind == list ]]; then
                    TU_LISTS[$section.$key]+="$value"$'\n'
                else
                    TU_VALUES[$section.$key]=$value
                fi
                ;;
        esac
    done < "$path"
}

test_uci_write() {
    local path=$1 section key item
    : > "$path"
    for section in "${TU_ORDER[@]}"; do
        printf "config %s '%s'\n" "${TU_TYPES[$section]}" "$section" >> "$path"
        for key in "${!TU_VALUES[@]}"; do
            [[ $key == "$section."* ]] || continue
            printf "\toption %s '%s'\n" "${key#*.}" "${TU_VALUES[$key]}" >> "$path"
        done
        for key in "${!TU_LISTS[@]}"; do
            [[ $key == "$section."* ]] || continue
            while IFS= read -r item; do
                [[ -n "$item" ]] || continue
                printf "\tlist %s '%s'\n" "${key#*.}" "$item" >> "$path"
            done <<< "${TU_LISTS[$key]}"
        done
        printf '\n' >> "$path"
    done
}

uci() {
    local config_dir="$TEST_CONFIG_DIR" command target package section option value path type number candidate found='' count=0 key
    while [[ ${1:-} == -* ]]; do
        case "$1" in -q) shift;; -c) config_dir=$2; shift 2;; *) return 2;; esac
    done
    command=${1:-}; shift || return 2
    target=${1:-}
    if [[ $command == commit ]]; then return 0; fi
    package=${target%%.*}; path="$config_dir/$package"
    test_uci_parse "$path" || return 2
    if [[ $command == add ]]; then
        section="cfg${#TU_ORDER[@]}"; TU_TYPES[$section]=$2; TU_ORDER+=("$section")
        test_uci_write "$path"; printf '%s\n' "$section"; return 0
    fi
    value=${target#*=}; target=${target%%=*}
    section=${target#*.}; section=${section%%.*}
    option=${target#"$package.$section"}; option=${option#.}
    if [[ $section == @* ]]; then
        type=${section#@}; type=${type%%\[*}; number=${section#*\[}; number=${number%\]}
        for candidate in "${TU_ORDER[@]}"; do
            [[ ${TU_TYPES[$candidate]} == "$type" ]] || continue
            if [[ $count == "$number" ]]; then found=$candidate; break; fi
            count=$((count + 1))
        done
        [[ -n "$found" ]] || return 1
        section=$found
    fi
    case "$command" in
        get)
            if [[ -z "$option" ]]; then [[ -v TU_TYPES[$section] ]] || return 1; printf '%s\n' "${TU_TYPES[$section]}"
            elif [[ -v TU_VALUES[$section.$option] ]]; then printf '%s\n' "${TU_VALUES[$section.$option]}"
            elif [[ -v TU_LISTS[$section.$option] ]]; then printf '%s' "${TU_LISTS[$section.$option]}"
            else return 1; fi
            ;;
        show)
            [[ -v TU_TYPES[$section] ]] || return 1
            printf '%s.%s=%s\n' "$package" "$section" "${TU_TYPES[$section]}"
            for key in "${!TU_VALUES[@]}"; do
                [[ $key == "$section."* ]] || continue
                printf "%s.%s='%s'\n" "$package" "$key" "${TU_VALUES[$key]}"
            done
            ;;
        set)
            if [[ -z "$option" ]]; then
                if [[ ! -v TU_TYPES[$section] ]]; then TU_ORDER+=("$section"); fi
                TU_TYPES[$section]=$value
            else
                [[ -v TU_TYPES[$section] ]] || return 1
                TU_VALUES[$section.$option]=$value
            fi
            test_uci_write "$path"
            ;;
        delete)
            unset 'TU_VALUES[$section.$option]' 'TU_LISTS[$section.$option]'
            test_uci_write "$path"
            ;;
        *) printf 'unexpected UCI command: %s\n' "$command" >&2; return 2;;
    esac
}
