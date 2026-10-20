verify_sha256_checksum() {
    local file="$1"
    local expected_name="$2"
    local checksum_url="$3"
    local ua="${4:-$DEFAULT_UA}"

    [ -z "$file" ] || [ -z "$checksum_url" ] && return 0
    [ -s "$file" ] || return 0

    local expected_hash
    expected_hash=$(curl -sL -m 15 --connect-timeout 5 -H "User-Agent: $ua" "$checksum_url" 2>/dev/null \
        | awk -v n="$expected_name" '$2 ~ n {print $1; exit} $0 ~ n {print $1; exit}')

    if [ -z "$expected_hash" ]; then
        LOG_WARN "Checksum file unavailable or entry not found, skip verification for【$expected_name】"
        return 0
    fi

    local actual_hash
    actual_hash=$(sha256sum "$file" 2>/dev/null | awk '{print $1}')
    if [ -z "$actual_hash" ]; then
        LOG_WARN "Unable to compute checksum, skip verification for【$expected_name】"
        return 0
    fi
    if [ "$actual_hash" = "$expected_hash" ]; then
        LOG_OUT "Checksum Verification Successful for【$expected_name】"
        return 0
    fi

    LOG_ERROR "Checksum mismatch for【$expected_name】(expected【$expected_hash】,got【$actual_hash】)"
    return 1
}
