#!/usr/bin/lua

------------------------------------------------
-- This file is part of the luci-app-ssr-plus update.lua
-- By Mattraks
------------------------------------------------
require "luci.sys"
require "luci.model.uci"
local function shell_quote(value)
    return "'" .. tostring(value):gsub("'", "'\"'\"'") .. "'"
end

-- The Lua worker owns FD8 for its whole transaction. A forged environment
-- marker cannot skip locking: verify the descriptor and the held lock first.
if os.getenv("SSRP_UPDATER_LOCKED") ~= "1" then
    local argument = arg[1] and (" " .. shell_quote(arg[1])) or ""
    local command = "( umask 077; exec 8>>/var/lock/ssrplus-update.lock && " ..
        "flock -w 30 -x 8 && SSRP_UPDATER_LOCKED=1 /usr/bin/lua " ..
        "/usr/share/shadowsocksr/update.lua" .. argument .. " )"
    os.exit(luci.sys.call(command))
end
if luci.sys.call('fd=$(readlink -f /proc/self/fd/8) && lock=$(readlink -f /var/lock/ssrplus-update.lock) && [ -n "$fd" ] && [ "$fd" = "$lock" ] && flock -n -x 8') ~= 0 then
    os.exit(1)
end

-- curl before 8.4 cannot cap unknown-length transfers. Refuse that runtime
-- before allocating scratch or downloading, rather than implying a byte bound.
local curl_major, curl_minor = luci.sys.exec("curl --version 8>&-"):match("^curl (%d+)%.(%d+)")
curl_major, curl_minor = tonumber(curl_major) or 0, tonumber(curl_minor) or 0
if curl_major < 8 or (curl_major == 8 and curl_minor < 4) then
    print("SSR updater requires curl 8.4 or newer for bounded downloads")
    os.exit(1)
end

local update_root = luci.sys.exec("mktemp -d /tmp/ssr-update.XXXXXX"):gsub("%s+$", "")
if not update_root:match("^/tmp/ssr%-update%.[%w]+$") then
    error("Unable to create private SSR update directory")
end
local update_id = update_root:match("([^/]+)$")
local function finish(code)
    os.remove(update_root .. "/ssr-update.tmp")
    os.remove(update_root)
    os.exit(code)
end
local update_status = 0
local icount = 0
local args = arg[1]
local uci = require "luci.model.uci".cursor()

local TMP_PATH = "/var/etc/ssrplus"
-- match comments/title/whitelist/ip address/excluded_domain
local comment_pattern = "^[!\\[@]+"
local ip_pattern = "^%d+%.%d+%.%d+%.%d+"
local domain_pattern = "([%w%-%_]+%.[%w%.%-%_]+)[%/%*]*"
local excluded_domain = {
    "apple.com", "sina.cn", "sina.com.cn", "baidu.com", "byr.cn", "jlike.com", 
    "weibo.com", "zhongsou.com", "youdao.com", "sogou.com", "so.com", "soso.com", 
    "aliyun.com", "taobao.com", "jd.com", "qq.com"
}
-- gfwlist parameter
local mydnsip = '127.0.0.1'
local mydnsport = '5335'
local ipsetname = 'gfwlist'
local new_appledns = uci:get_first("shadowsocksr", "global", "apple_dns")
local bc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
-- base64decoding
local function base64_dec(data)
	data = string.gsub(data, '[^' .. bc .. '=]', '')
	return (data:gsub('.', function(x)
		if (x == '=') then
			return ''
		end
		local r, f = '', (bc:find(x) - 1)
		for i = 6, 1, -1 do
			r = r .. (f % 2 ^ i - f % 2 ^ (i - 1) > 0 and '1' or '0')
		end
		return r;
	end):gsub('%d%d%d?%d?%d?%d?%d?%d?', function(x)
		if (#x ~= 8) then
			return ''
		end
		local c = 0
		for i = 1, 8 do
			c = c + (x:sub(i, i) == '1' and 2 ^ (8 - i) or 0)
		end
		return string.char(c)
	end))
end
-- check if domain is excluded
local function check_excluded_domain(value)
	for _, domain in ipairs(excluded_domain) do
		if value:find(domain) then
			return true
		end
	end
end
-- gfwlist转码至dnsmasq格式
local function generate_gfwlist(type)
    local domains, domains_map = {}, {}
    local out = io.open(update_root .. "/ssr-update." .. type, "w")
    for line in io.lines(update_root .. "/ssr-update.tmp") do
        if not (string.find(line, comment_pattern) or string.find(line, ip_pattern) or check_excluded_domain(line)) then
            local start, finish, match = string.find(line, domain_pattern)
            if start and not domains_map[match] then
                domains_map[match] = true
                table.insert(domains, match)
            end
        end
    end
    for _, domain in ipairs(domains) do
        out:write(string.format("server=/%s/%s#%s\n", domain, mydnsip, mydnsport))
        out:write(string.format("ipset=/%s/%s\n", domain, ipsetname))
    end
    out:close()
    os.remove(update_root .. "/ssr-update.tmp")
end

-- 更换 Apple dns
local function generate_apple(type)
	local domains, domains_map = {}, {}
	local out = io.open(update_root .. "/ssr-update." .. type, "w")
	for line in io.lines(update_root .. "/ssr-update.tmp") do
		if not (string.find(line, comment_pattern)) then
			local start, finish, match = string.find(line, domain_pattern)
			if start and not domains_map[match] then
				domains_map[match] = true
				match = string.gsub(match, "%s", "") --从域名中去除所有空白字符
				table.insert(domains, match)
			end
		end
	end
	for _, domain in ipairs(domains) do
        if new_appledns and new_appledns ~= "" then
            out:write(string.format("server=/%s/%s\n", domain, new_appledns))
        end
	end
	out:close()
	os.remove(update_root .. "/ssr-update.tmp")
end

-- adblock转码至dnsmasq格式
local function generate_adblock(type)
	local domains, domains_map = {}, {}
	local out = io.open(update_root .. "/ssr-update." .. type, "w")
	for line in io.lines(update_root .. "/ssr-update.tmp") do
		if not (string.find(line, comment_pattern)) then
			local start, finish, match = string.find(line, domain_pattern)
			if start and not domains_map[match] then
				domains_map[match] = true
				table.insert(domains, match)
			end
		end
	end
	for _, domain in ipairs(domains) do
		out:write(string.format("address=/%s/\n", domain))
	end
	out:close()
	os.remove(update_root .. "/ssr-update.tmp")
end

local log = function(...)
	if select(1, ...) == -1 then update_status = 1 end
	if args then
		print("{ret=" .. table.concat({...}, ",retcount=") .. "}")
	else
		print(os.date("%Y-%m-%d %H:%M:%S ") .. table.concat({...}, " "))
	end
end

local MAX_DOWNLOAD = 16777216
local function call(command)
    -- The worker keeps FD8. Network/init children must not leak it to daemons.
    return luci.sys.call(command .. " 8>&-")
end
local function read_file(path)
    local input = assert(io.open(path, "rb"))
    local data = input:read(MAX_DOWNLOAD + 1) or ""
    input:close()
    assert(#data <= MAX_DOWNLOAD, "rule download exceeds size limit")
    return data
end
local function write_file(path, data)
    local output = assert(io.open(path, "wb"))
    local written, message = output:write(data)
    local closed, close_message = output:close()
    assert(written and closed, message or close_message or "rule write failed")
end
local function hash(path)
    return luci.sys.exec("md5sum " .. shell_quote(path) .. " 8>&- | awk '{print $1}'"):gsub("%s+$", "")
end
local function envelope(data)
    assert(data:find("%S"), "rule download is empty")
    assert(not data:find("%z") and not data:find("<[%a!/?][^>]*>"), "rule download is HTML or binary")
end
local function valid_v4(value)
    local a, b, c, d = value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return false end
    for _, part in ipairs({a, b, c, d}) do
        if #part > 3 or tonumber(part) > 255 then return false end
    end
    return true
end
local function valid_domain(value)
    value = value:gsub("^%*%.", ""):gsub("^%.", ""):gsub("%.$", "")
    if #value > 253 or not value:find("%.") or value:find("[^%w_.%-]") or value:find("%.%.") then return false end
    for label in value:gmatch("[^.]+") do
        if #label > 63 or label:match("^%-") or label:match("%-$") then return false end
    end
    return value ~= ""
end
local function validate_rules(data, kind)
    envelope(data)
    local count = 0
    for line in (data .. "\n"):gmatch("([^\n]*)\n") do
        line = line:gsub("^%s+", ""):gsub("%s+$", "")
        if line ~= "" and not line:match("^[#!]") then
            if kind == "ip_data" or kind == "nfip_data" then
                local address, bits = line:match("^([^/]+)/(%d+)$")
                assert(address and valid_v4(address) and tonumber(bits) <= 32, "invalid IPv4 CIDR rule")
            else
                local directive, domain, target = line:match("^(%a+)=/([^/]+)/([^%s/]*)$")
                assert(domain and valid_domain(domain), "invalid DNS domain rule")
                if kind == "gfw_data" then
                    assert((directive == "server" and target == "127.0.0.1#5335") or
                        (directive == "ipset" and target == "gfwlist"), "invalid GFW directive")
                elseif kind == "apple_data" then
                    assert(directive == "server" and valid_v4(target), "invalid Apple DNS directive")
                else
                    assert(directive == "address" and (target == "" or target == "#" or valid_v4(target)), "invalid adblock directive")
                end
            end
            count = count + 1
        end
    end
    assert(count > 0, "rule conversion produced no rules")
    return count
end

-- Canonical sources are a transaction too: a failed activation restores the
-- previous complete source. Keep the candidate in .pending for diagnosis/retry.
local function update(url, file, kind, file2)
    local downloaded = update_root .. "/ssr-update." .. kind
    local staged = file .. "." .. update_id
    local backup = file .. ".previous." .. update_id
    local pending = file .. ".pending"
    local keep_backup = false
    local ok, message = pcall(function()
        assert(type(url) == "string" and url:match("^https?://"), "invalid rule URL")
        local command = "curl -f -sSL --insecure --connect-timeout 5 --max-time 30 " ..
            "--max-filesize " .. MAX_DOWNLOAD .. " --proto '=http,https' --proto-redir '=http,https' -o " ..
            shell_quote(downloaded) .. " -- " .. shell_quote(url)
        assert(call(command) == 0, "rule download failed")
        local raw = read_file(downloaded)
        envelope(raw)
        if kind == "gfw_data" or kind == "apple_data" then
            if raw:match("^[%w+/%s=]+$") then raw = base64_dec(raw) end
            envelope(raw)
            write_file(update_root .. "/ssr-update.tmp", raw)
            if kind == "gfw_data" then generate_gfwlist(kind) else generate_apple(kind) end
        elseif kind == "ad_data" and not raw:find("address=", 1, true) then
            write_file(update_root .. "/ssr-update.tmp", raw)
            generate_adblock(kind)
        end
        local candidate = read_file(downloaded)
        local count = validate_rules(candidate, kind)
        local candidate_hash, old_hash = hash(downloaded), hash(file)
        assert(candidate_hash ~= "", "unable to hash rule candidate")
        local changed = candidate_hash ~= old_hash
        write_file(pending, candidate)
        if changed then
            if old_hash ~= "" then
                assert(call("cp -f " .. shell_quote(file) .. " " .. shell_quote(backup)) == 0, "source backup failed")
            end
            assert(call("cp -f " .. shell_quote(pending) .. " " .. shell_quote(staged) ..
                " && mv -f " .. shell_quote(staged) .. " " .. shell_quote(file)) == 0, "source publication failed")
        end
        -- Every type, including China/Netflix IP lists, activates under the
        -- service lifecycle lock. Never call chinaipset directly from here.
        if call("/etc/init.d/shadowsocksr reload") ~= 0 then
            if changed and hash(file) == candidate_hash then
                if old_hash ~= "" then
                    keep_backup = true
                    assert(call("mv -f " .. shell_quote(backup) .. " " .. shell_quote(file)) == 0,
                        "activation and canonical rollback failed; old source backup retained")
                    keep_backup = false
                else
                    assert(os.remove(file), "activation failed; unable to remove new canonical source")
                end
            elseif changed then
                log("activation failed; newer external canonical write preserved")
            end
            error("rule activation failed; pending candidate retained")
        end
        assert(os.remove(pending), "activated rules but unable to clear pending candidate")
        if args then log(changed and 0 or 1, kind == "gfw_data" and count / 2 or count)
        else log("规则更新及激活成功") end
    end)
    os.remove(downloaded)
    os.remove(update_root .. "/ssr-update.tmp")
    os.remove(staged)
    if not keep_backup then os.remove(backup) end
    if not ok then
        log(-1)
        if not args then log(tostring(message)) end
    end
end

if args then
	if args == "gfw_data" then
		update(uci:get_first("shadowsocksr", "global", "gfwlist_url"), "/etc/ssrplus/gfw_list.conf", args)
		finish(update_status)
	end
	if args == "ip_data" then
		update(uci:get_first("shadowsocksr", "global", "chnroute_url"), "/etc/ssrplus/china_ssr.txt", args, TMP_PATH .. "/china_ssr.txt")
		finish(update_status)
	end
	if args == "apple_data" then
		update(uci:get_first("shadowsocksr", "global", "apple_url"), "/etc/ssrplus/applechina.conf", args)
		finish(update_status)
	end
	if args == "ad_data" then
		update(uci:get_first("shadowsocksr", "global", "adblock_url"), "/etc/ssrplus/ad.conf", args)
		finish(update_status)
	end
	if args == "nfip_data" then
		update(uci:get_first("shadowsocksr", "global", "nfip_url"), "/etc/ssrplus/netflixip.list", args)
		finish(update_status)
	end
else
	log("正在更新【GFW列表】数据库")
	update(uci:get_first("shadowsocksr", "global", "gfwlist_url"), "/etc/ssrplus/gfw_list.conf", "gfw_data")
	log("正在更新【国内IP段】数据库")
	update(uci:get_first("shadowsocksr", "global", "chnroute_url"), "/etc/ssrplus/china_ssr.txt", "ip_data", TMP_PATH .. "/china_ssr.txt")
	if uci:get_first("shadowsocksr", "global", "apple_optimization", "0") == "1" then
		log("正在更新【Apple域名】数据库")
		update(uci:get_first("shadowsocksr", "global", "apple_url"), "/etc/ssrplus/applechina.conf", "apple_data")
	end
	if uci:get_first("shadowsocksr", "global", "adblock", "0") == "1" then
		log("正在更新【广告屏蔽】数据库")
		update(uci:get_first("shadowsocksr", "global", "adblock_url"), "/etc/ssrplus/ad.conf", "ad_data")
	end
	if uci:get_first("shadowsocksr", "global", "netflix_enable", "0") == "1" then
		log("正在更新【Netflix IP段】数据库")
		update(uci:get_first("shadowsocksr", "global", "nfip_url"), "/etc/ssrplus/netflixip.list", "nfip_data")
	end
	-- log("正在更新【Netflix IP段】数据库")
	-- update(uci:get_first("shadowsocksr", "global", "nfip_url"), "/etc/ssrplus/netflixip.list", "nfip_data")
end

finish(update_status)
