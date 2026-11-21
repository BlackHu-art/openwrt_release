// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2026 rule2c <rule2c@gmail.com>
 */
'use strict';
'require view';
'require fs';
'require uci';
'require form';
'require poll';
'require dom';
'require network';
'require ui';

// ── 服务状态 ──────────────────────────────────────────────────────────────────

function checkNetControlProcess() {
    // 用自定义的 service_state 命令（综合总开关 + 守护进程），不用 status——
    // 后者在部分版本会被 rc.common 的内置 status 覆盖。
    // state：running / disabled（总开关关闭）/ stopped（开关开但进程已退出）
    return fs.exec('/etc/init.d/netcontrol', ['service_state']).then(function(res) {
        var out = (res.stdout || '').trim();
        return { state: (out === 'running' || out === 'disabled' || out === 'stopped') ? out : 'error' };
    }).catch(function() {
        return { state: 'error' };
    });
}

// 返回 DOM 节点而不是 HTML 字符串，避免走 innerHTML
var SERVICE_STATES = {
    running:  { mark: '✓', color: '#3d8b40', label: 'RUNNING' },
    disabled: { mark: '○', color: '#888888', label: 'DISABLED' },
    stopped:  { mark: '✗', color: '#d9534f', label: 'NOT RUNNING' }
};

function renderServiceStatus(state) {
    var s = SERVICE_STATES[state] || SERVICE_STATES.stopped;
    return E('span', { 'style': 'color:' + s.color + ';font-style:italic' }, [
        s.mark + ' ',
        E('strong', {}, [_('NetControl Service'), ' ', _(s.label)])
    ]);
}

// ── 随机 MAC 识别 ─────────────────────────────────────────────────────────────

// 厂商烧录的 MAC 第一个字节的 0x02 位为 0，系统随机生成的为 1（IEEE 的
// local/universal 标志）。0x01 位是组播标志，源地址不会置位，一并排除。
function isRandomMac(mac) {
    var m = /^([0-9a-fA-F]{2}):/.exec(String(mac || '').trim());
    if (!m) return false;
    var b = parseInt(m[1], 16);
    return (b & 0x02) !== 0 && (b & 0x01) === 0;
}

function collectRandomHosts(hosts) {
    var out = [];
    Object.keys(hosts || {}).forEach(function(hwaddr) {
        if (!isRandomMac(hwaddr)) return;
        var host = hosts[hwaddr] || {};
        var addrs = L.toArray(host.ipaddrs || host.ipv4 || []);
        out.push({ mac: hwaddr.toLowerCase(), name: host.name || '', addr: addrs[0] || '' });
    });
    out.sort(function(a, b) { return a.mac.localeCompare(b.mac); });
    return out;
}

// 随机 MAC 设备一览。被拦下的设备只是突然没网，界面上必须能一眼看出是谁、为什么。
function renderRandomMacTable(randomHosts, blockOn, allowSet) {
    if (!randomHosts.length) return null;

    var blockedCount = 0;
    var rows = [E('tr', { 'class': 'tr table-titles' }, [
        E('th', { 'class': 'th' }, _('Device')),
        E('th', { 'class': 'th' }, _('MAC Address')),
        E('th', { 'class': 'th' }, _('IP Address')),
        E('th', { 'class': 'th' }, _('Status'))
    ])];

    randomHosts.forEach(function(h) {
        var statusEl;
        if (!blockOn)
            statusEl = E('span', { 'style': 'color:#888' }, _('Blocking disabled'));
        else if (allowSet[h.mac])
            statusEl = E('span', { 'style': 'color:#3d8b40' }, _('Allowed'));
        else {
            blockedCount++;
            statusEl = E('span', { 'style': 'color:#d9534f' }, _('Blocked'));
        }
        rows.push(E('tr', { 'class': 'tr' }, [
            E('td', { 'class': 'td' }, h.name || _('Unknown device')),
            E('td', { 'class': 'td' }, h.mac),
            E('td', { 'class': 'td' }, h.addr || '-'),
            E('td', { 'class': 'td' }, statusEl)
        ]));
    });

    var note = blockOn
        ? (_('Blocked devices can still reach the router but have no internet access.') + ' '
           + _('Currently blocked:') + ' ' + blockedCount)
        : _('These devices would be blocked if you enable the switch above. Fill the allowlist first.');

    return E('div', { 'class': 'cbi-section', 'id': 'nc_random_mac' }, [
        E('h3', {}, _('Devices Using a Randomized MAC')),
        E('p', { 'style': 'color:#888' }, note),
        E('div', { 'class': 'table-wrapper' },
            E('table', { 'class': 'table cbi-section-table' }, rows))
    ]);
}

// ── 法定节假日 ────────────────────────────────────────────────────────────────

// 解析 netcontrol holiday-info 的单行输出：
//   today=2026-10-01 type=off source=online years="2025 2026"
function parseHolidayInfo(out) {
    var info = {};
    String(out || '').replace(/(\w+)=("([^"]*)"|\S*)/g, function(all, k, v, q) {
        info[k] = (q !== undefined) ? q : v;
    });
    return info.today ? info : null;
}

var HOLIDAY_SOURCES = {
    custom:  _('custom day'),
    online:  _('online data'),
    bundled: _('bundled data')
};

function renderHolidayInfo(info) {
    if (!info)
        return E('span', { 'style': 'color:#888' }, _('Holiday data status unavailable'));
    var parts = [
        _('Today') + ' ' + info.today + '：',
        E('strong', {}, info.type === 'off' ? _('Day off') : _('Workday (statutory)'))
    ];
    if (info.source === 'weekday')
        parts.push(E('span', { 'style': 'color:#d9534f' },
            '（' + _('no holiday data for this year, Monday to Friday treated as workdays') + '）'));
    else
        parts.push('（' + (HOLIDAY_SOURCES[info.source] || info.source) + '）');
    parts.push(E('br'), _('Years with data:') + ' ' + (info.years || '-'));
    return E('span', {}, parts);
}

// ── 设备状态表 ────────────────────────────────────────────────────────────────

function renderStatusTable(content) {
    if (!content || !content.trim()) {
        return E('p', { 'class': 'alert-message' }, _('No device data available.'));
    }

    var rows = [E('tr', { 'class': 'tr table-titles' }, [
        E('th', { 'class': 'th' }, _('Device')),
        E('th', { 'class': 'th' }, _('Status')),
        E('th', { 'class': 'th' }, _('Time Used')),
        E('th', { 'class': 'th' }, _('Time Limit')),
        E('th', { 'class': 'th' }, _('Action'))
    ])];

    var visibleCount = 0;
    var seenTargets = {};
    content.trim().split('\n').forEach(function(line) {
        var p = line.split('\t');
        if (p.length < 7) return;

        var target   = p[0];
        var blocked  = p[1] === '1';
        var usedMin  = p[2];
        var maxMin   = p[3];
        var comment  = p[4];
        var enabled  = p[5] === '1';
        var timeMode = p[6];

        if (!target || !enabled) return;
        if (seenTargets[target]) return;
        seenTargets[target] = true;
        visibleCount++;

        var label = comment ? (comment + ' (' + target + ')') : target;

        var statusEl = blocked
            ? E('span', { 'style': 'color:#d9534f;font-weight:bold' }, '● ' + _('Blocked'))
            : E('span', { 'style': 'color:#5cb85c;font-weight:bold' }, '● ' + _('Allowed'));

        // 以后端是否输出了实际数值为准：没有时长维度的规则后端写 "-"
        var hasDuration = (timeMode === 'duration' || timeMode === 'combined') && usedMin !== '-';
        var usedEl  = hasDuration ? (usedMin + ' ' + _('min')) : '-';
        var limitEl = hasDuration ? (maxMin  + ' ' + _('min')) : '-';

        var actionEl;
        if (hasDuration) {
            actionEl = E('button', {
                'class': 'btn cbi-button cbi-button-action',
                'style': 'padding:4px 12px',
                'click': (function(tgt) {
                    return function(ev) {
                        var btn = ev.currentTarget;
                        btn.disabled = true;
                        btn.textContent = _('Resetting...');
                        fs.exec_direct('/usr/libexec/netcontrol-call', ['reset_duration', tgt])
                            .then(function() { btn.textContent = _('Reset'); btn.disabled = false; })
                            .catch(function() { btn.textContent = _('Reset'); btn.disabled = false; });
                    };
                })(target)
            }, _('Reset'));
        } else {
            actionEl = E('span', {}, '-');
        }

        rows.push(E('tr', { 'class': 'tr' }, [
            E('td', { 'class': 'td' }, label),
            E('td', { 'class': 'td' }, statusEl),
            E('td', { 'class': 'td' }, usedEl),
            E('td', { 'class': 'td' }, limitEl),
            E('td', { 'class': 'td' }, actionEl)
        ]));
    });

    if (visibleCount === 0) {
        rows.push(E('tr', { 'class': 'tr' }, [
            E('td', { 'class': 'td', 'colspan': '5', 'style': 'text-align:center;color:#888' },
                _('No enabled devices.'))
        ]));
    }

    return E('div', { 'class': 'table-wrapper' },
        E('table', { 'class': 'table cbi-section-table' }, rows)
    );
}

// ── 主视图 ────────────────────────────────────────────────────────────────────

return view.extend({
    load: function() {
        return Promise.all([
            uci.load('netcontrol'),
            network.getHostHints(),
            L.resolveDefault(fs.exec_direct('/usr/libexec/netcontrol-call', ['holiday_info']), '')
        ]);
    },

    render: function(data) {
        var m, s, o;
        var hints = data[1] || {};
        var hosts = hints.hosts || hints;
        var holidayInfo = parseHolidayInfo(data[2]);
        var randomHosts = collectRandomHosts(hosts);
        var globalCfg = uci.sections('netcontrol', 'netcontrol')[0] || {};
        var allowSet = {};
        L.toArray(globalCfg.rand_mac_allow).forEach(function(m) {
            allowSet[String(m).trim().toLowerCase()] = true;
        });
        var randomMacSection = renderRandomMacTable(
            randomHosts, globalCfg.rand_mac_block === '1', allowSet);

        // ── 服务状态（行内，注入到启用开关之后） ──
        var serviceStatusView = E('span', {
            'id': 'service_status',
            'style': 'margin-left:1em;vertical-align:middle'
        }, E('span', { 'class': 'spinning' }, ' '));

        function refreshServiceStatus() {
            return checkNetControlProcess().then(function(res) {
                dom.content(serviceStatusView, renderServiceStatus(res.state));
            }).catch(function() {
                dom.content(serviceStatusView,
                    E('span', { 'style': 'color:#e0a800' }, '⚠ ' + _('Status check failed')));
            });
        }
        refreshServiceStatus();

        // 15 秒一次：这一路要在路由器上跑一遍 /etc/init.d/netcontrol，比读状态文件贵
        poll.add(refreshServiceStatus, 15);

        // ── 设备实时状态表（form 外部独立 DOM） ──
        var tableWrap = E('div', { 'id': 'tc_status_table' },
            E('p', { 'style': 'color:#888' }, _('Loading device status...'))
        );

        function refreshStatus() {
            return fs.read_direct('/var/lib/netcontrol/device_status.tsv', 'text')
                .then(function(content) {
                    dom.content(tableWrap, renderStatusTable(content));
                })
                .catch(function() {
                    dom.content(tableWrap, E('p', { 'style': 'color:#888' },
                        _('Status unavailable (service may not be running)')));
                });
        }

        refreshStatus();
        poll.add(refreshStatus, 5);
        poll.start();

        // id 供样式表定位用
        var deviceStatusSection = E('div', { 'class': 'cbi-section', 'id': 'nc_device_status' }, [
            E('h3', {}, _('Device Status')),
            tableWrap
        ]);

        // ── Form ──（不传 title：左侧菜单已有同名入口）
        m = new form.Map('netcontrol');

        // ── 全局设置 ──
        s = m.section(form.TypedSection, 'netcontrol');
        s.anonymous = true;
        s.addremove = false;

        o = s.option(form.Flag, 'enabled', _('Enable Time Control'),
            _('Master switch. Disabling will immediately stop all control rules and allow all devices to access the internet freely.'));
        o.rmempty = false;
        o.default = '0';

        o = s.option(form.ListValue, 'chain', _('Control Intensity'),
            _('Strong mode also blocks traffic addressed to the router itself, so a blocked device loses access to this web interface as well.'));
        o.value('forward', _('Ordinary forward control'));
        o.value('input',   _('Strong input control'));
        o.default = 'forward';
        o.rmempty = false;

        o = s.option(form.Flag, 'rand_mac_block', _('Block Randomized MAC Devices'),
            _('When enabled, every device using a randomized MAC is denied internet access unless listed below.')
            + ' ' + _('Currently detected:') + ' ' + randomHosts.length);
        o.default = '0';
        o.rmempty = false;

        o = s.option(form.DynamicList, 'rand_mac_allow', _('Randomized MAC Allowlist'),
            _('Devices here keep internet access even with a randomized MAC. A device dropping off the list whenever it re-randomizes is expected behaviour.'));
        o.depends('rand_mac_block', '1');
        o.rmempty = true;
        randomHosts.forEach(function(h) {
            var extra = [h.name, h.addr].filter(function(x) { return x; }).join(' · ');
            o.value(h.mac, extra ? (h.mac + ' · ' + extra) : h.mac);
        });
        o.validate = function(section_id, value) {
            if (value == null || value === '') return true;
            if (!/^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$/.test(value.trim()))
                return _('Invalid MAC address format');
            return isRandomMac(value) ? true
                : _('This is not a randomized MAC address; the allowlist has no effect on it.');
        };

        // ── 法定节假日 ──
        o = s.option(form.DummyValue, '_holiday_status', _('Statutory Holidays'),
            _('Used by the "Statutory workday" and "Statutory day off" options of device rules. Holidays and make-up workdays follow the State Council schedule.'));
        o.renderWidget = function() {
            var box = E('span', {}, renderHolidayInfo(holidayInfo));
            var btn = E('button', {
                'class': 'btn cbi-button cbi-button-action',
                'style': 'margin-left:1em',
                'click': function(ev) {
                    ev.preventDefault();
                    btn.disabled = true;
                    btn.textContent = _('Updating...');
                    fs.exec_direct('/usr/libexec/netcontrol-call', ['holiday_update'])
                        .then(function(out) {
                            holidayInfo = parseHolidayInfo(out) || holidayInfo;
                            dom.content(box, renderHolidayInfo(holidayInfo));
                        })
                        .catch(function(err) {
                            ui.addNotification(null, E('p', _('Holiday data update failed: %s').format(err)), 'warning');
                        })
                        .then(function() { btn.textContent = _('Update now'); btn.disabled = false; });
                }
            }, _('Update now'));
            return E('div', {}, [box, btn]);
        };

        o = s.option(form.Flag, 'holiday_update', _('Auto-update Holiday Data'),
            _('Download the latest holiday schedule once a day, only while some rule uses the statutory options. Without network access the bundled data is used.'));
        o.default = '1';
        o.rmempty = false;

        o = s.option(form.Value, 'holiday_url', _('Holiday Data URL'),
            _('{year} is replaced by the year. Must serve the holiday-cn JSON format.'));
        o.placeholder = 'https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json';
        o.depends('holiday_update', '1');
        o.rmempty = true;
        o.validate = function(section_id, value) {
            if (value == null || value === '') return true;
            return /^https?:\/\/\S*\{year\}\S*$/.test(value.trim())
                ? true : _('Must be an http(s) URL containing {year}');
        };

        o = s.option(form.DynamicList, 'holiday_extra', _('Custom Days'),
            _('Overrides the holiday data for single days, e.g. 2026-12-31:off for an extra day off or 2026-12-27:work for a working weekend.'));
        o.placeholder = 'YYYY-MM-DD:off';
        o.rmempty = true;
        o.validate = function(section_id, value) {
            if (value == null || value === '') return true;
            var m = /^(\d{4})-(\d{2})-(\d{2}):(off|work)$/.exec(value.trim());
            if (!m) return _('Expected YYYY-MM-DD:off or YYYY-MM-DD:work');
            var d = new Date(+m[1], +m[2] - 1, +m[3]);
            return (d.getMonth() === +m[2] - 1 && d.getDate() === +m[3])
                ? true : _('Invalid date');
        };

        // ── 设备规则表 ──
        s = m.section(form.TableSection, 'device', _('Device Rules'));
        s.addremove = true;
        s.anonymous = true;
        s.sortable  = false;

        // 列宽不能用 o.width（本版 LuCI 的 TableSection 会忽略），统一由下方
        // colPct + applyColumnWidths() 写入行内样式；增删列时那个数组必须同步改。
        o = s.option(form.Value, 'comment', _('Comment'));
        o.optional = true;
        o.placeholder = _('Description');

        o = s.option(form.Flag, 'enable', _('Enabled'));
        o.rmempty = false;
        o.default = '1';

        // 用 ListValue 而不是带候选值的 Value：前者渲染成原生 <select>，后者会被
        // 渲染成 ui.Combobox 浮层，定位与列宽都要自己兜底。
        // 代价：原生 select 不能手工输入，新增未探测到的地址要走 uci 命令行。
        o = s.option(form.ListValue, 'target', _('IP/MAC Address'));
        o.rmempty = false;
        // 校验：单个 IPv4 / CIDR / IPv4 范围 / MAC / IPv6(可带前缀)，与后端 parse_target 保持一致
        o.validate = function(section_id, value) {
            if (value == null || value === '') return _('IP/MAC address is required');
            var v = value.trim();
            var reIpv4      = /^(\d{1,3}\.){3}\d{1,3}$/;
            var reIpv4Cidr  = /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/;
            var reIpv4Range = /^(\d{1,3}\.){3}\d{1,3}-(\d{1,3}\.){3}\d{1,3}$/;
            var reMac       = /^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$/;
            var reIpv6      = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(\/\d{1,3})?$/;
            function octetsOk(s) {
                return s.split(/[.\-\/]/).every(function(p) {
                    return !/^\d+$/.test(p) || parseInt(p, 10) <= 255;
                });
            }
            if (reIpv4.test(v) || reIpv4Range.test(v))
                return octetsOk(v) ? true : _('Invalid IPv4 address (octet exceeds 255)');
            if (reIpv4Cidr.test(v)) {
                if (!octetsOk(v.split('/')[0]))
                    return _('Invalid IPv4 address (octet exceeds 255)');
                // 掩码与后端 parse_target 同步校验，否则保存成功但后端静默拒绝、设备永不被拦截
                return parseInt(v.split('/')[1], 10) <= 32
                    ? true : _('Invalid IPv4 prefix length (0-32)');
            }
            if (reMac.test(v)) return true;
            if (reIpv6.test(v)) {
                var p6 = v.split('/');
                return (p6.length < 2 || parseInt(p6[1], 10) <= 128)
                    ? true : _('Invalid IPv6 prefix length (0-128)');
            }
            return _('Invalid IP/MAC address format');
        };
        // 把 DHCP/邻居发现探到的主机铺成下拉候选。
        // 每台主机出两类候选：一条按 MAC（换 IP 也能跟住），每个 IP 各一条。
        var picks = [];
        Object.keys(hosts || {}).forEach(function(hwaddr) {
            var host = hosts[hwaddr] || {};
            var label = host.name ? (' · ' + host.name) : '';
            var addrs = L.toArray(host.ipaddrs || host.ipv4 || []);
            if (!addrs.length) return;
            picks.push({
                group: 1,
                value: hwaddr,
                text: hwaddr + label + (isRandomMac(hwaddr) ? (' · ' + _('random MAC')) : '')
            });
            addrs.forEach(function(addr) {
                picks.push({ group: 0, value: addr, text: addr + label });
            });
        });

        // IP 排在 MAC 前面（group 升序），组内按标签排序；同一地址只保留一条
        picks.sort(function(a, b) {
            return (a.group - b.group) || a.text.localeCompare(b.text);
        });
        var seenAddr = {};
        picks.forEach(function(p) {
            if (seenAddr[p.value]) return;
            seenAddr[p.value] = true;
            o.value(p.value, p.text);
        });

        // 已保存但不在候选表里的地址必须补成候选项：原生 select 只能选候选里有的值，
        // 否则已保存的配置会显示成空白，一点保存就被抹掉。
        uci.sections('netcontrol', 'device').forEach(function(sec) {
            var t = (sec.target || '').trim();
            if (!t || seenAddr[t]) return;
            seenAddr[t] = true;
            o.value(t, t);
        });

        o = s.option(form.ListValue, 'time_mode', _('Time Control Mode'));
        o.value('period',   _('Time Period Control (allow in period)'));
        o.value('duration', _('Allow Duration Control (allow limited time)'));
        o.value('combined', _('Combined Control (allow in period + limit duration)'));
        o.default = 'period';
        o.rmempty = false;

        var validateHHMM = function(section_id, value) {
            if (value == null || value === '') return true;   // 留空时回退到默认值
            return /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
                ? true : _('Invalid time, expected HH:MM (00:00-23:59)');
        };

        o = s.option(form.Value, 'timestart', _('Allow Start Time'));
        o.placeholder = '00:00';
        o.default = '00:00';
        o.validate = validateHHMM;
        o.depends('time_mode', 'period');
        o.depends('time_mode', 'combined');

        o = s.option(form.Value, 'timeend', _('Allow End Time'));
        o.placeholder = '00:00';
        o.default = '00:00';
        o.validate = validateHHMM;
        o.depends('time_mode', 'period');
        o.depends('time_mode', 'combined');

        o = s.option(form.Value, 'duration', _('Allowed Duration (minutes)'));
        o.placeholder = '60';
        o.default = '60';
        o.datatype = 'min(1)';
        o.depends('time_mode', 'duration');
        o.depends('time_mode', 'combined');

        o = s.option(form.ListValue, 'reset_cycle', _('Reset Cycle'));
        o.value('daily',   _('Daily Reset'));
        o.value('weekly',  _('Weekly Reset'));
        o.value('monthly', _('Monthly Reset'));
        o.value('never',   _('Never Reset (until manual reset)'));
        o.default = 'daily';
        o.depends('time_mode', 'duration');
        o.depends('time_mode', 'combined');

        o = s.option(form.ListValue, 'week', _('Week Day (1~7)'));
        o.value('0',         _('Everyday'));
        o.value('1',         _('Monday'));
        o.value('2',         _('Tuesday'));
        o.value('3',         _('Wednesday'));
        o.value('4',         _('Thursday'));
        o.value('5',         _('Friday'));
        o.value('6',         _('Saturday'));
        o.value('7',         _('Sunday'));
        o.value('1,2,3,4,5', _('Workday'));
        o.value('6,7',       _('Rest Day'));
        o.value('cn_work',   _('Statutory workday'));
        o.value('cn_off',    _('Statutory day off'));
        o.default = '0';
        o.rmempty = false;

        // 用 table-layout:fixed 按比例分配列宽，并把控件收进单元格内
        // （min-width 必须清零，主题 CSS 会给输入框设最小宽度）。
        var tableCss = `
            /* 撑满容器；具体列宽由 applyColumnWidths() 写的行内百分比决定。这里不写，
               因为样式表里的 #id .th:nth-child(n) 会被 Argon 主题盖掉。 */
            #cbi-netcontrol-device table {
                table-layout: fixed;
                width: 100%;
            }
            #cbi-netcontrol-device .th,
            #cbi-netcontrol-device .td {
                padding: 6px 6px !important;
                min-width: 0 !important;
                white-space: normal;
                word-break: break-word;
                vertical-align: middle;
            }
            /* 控件填满所在单元格。min-width 必须带 !important 清零：主题 CSS 会给
               输入框和 select 设最小宽度，压不掉的话列宽约束就失效了。 */
            #cbi-netcontrol-device .td input[type="text"],
            #cbi-netcontrol-device .td select {
                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;
                box-sizing: border-box;
            }
            /* 选项文字是「地址 · 主机名」，列窄时交给 select 自己截断，不撑破单元格 */
            #cbi-netcontrol-device .td select {
                text-overflow: ellipsis;
            }
        `;

        // 设备表各列占比，顺序即列顺序，合计 100：
        // 注释/已启用/IP·MAC/控制方式/开始/结束/时长/重置周期/星期/删除按钮。
        var colPct = [5, 5, 22, 17, 7, 7, 8, 10, 10, 9];

        // 按表格当前实际像素宽度换算成 px 写死，而不是写百分比或 em：
        // table-layout:fixed 下各列宽度之和不足表宽时，多出来的空间会按比例摊回，
        // 指定值就不作数了。让最后一列吃掉除法余数，各列之和恰好等于表宽。
        //
        // 表宽变化后必须重算，故 resize 时要再调用一次（见下方监听）。宽度只在
        // 初次渲染和 resize 时取（remeasure=true），其余场合复用缓存。
        var cachedWidths = null, cachedTotal = 0;

        function applyColumnWidths(root, remeasure) {
            var tbl = root.querySelector('#cbi-netcontrol-device table');
            if (!tbl) return;

            if (remeasure) {
                var total = tbl.clientWidth || tbl.offsetWidth;
                // 量到 0 说明尚未排版，放弃这一次；表宽没变则跳过重算，
                // 顺带断掉「写列宽 → 触发 ResizeObserver → 再写列宽」的自激循环。
                if (total && total !== cachedTotal) {
                    cachedTotal = total;
                    var list = [], acc = 0, i, w;
                    for (i = 0; i < colPct.length; i++) {
                        w = (i === colPct.length - 1) ? (total - acc)
                                                      : Math.floor(total * colPct[i] / 100);
                        list.push(w + 'px');
                        acc += w;
                    }
                    cachedWidths = list;
                }
            }

            if (!cachedWidths) return;
            var widths = cachedWidths;
            var rows = tbl.querySelectorAll('tr');
            for (var r = 0; r < rows.length; r++) {
                var cells = rows[r].children;
                for (var c = 0; c < cells.length && c < widths.length; c++)
                    cells[c].style.setProperty('width', widths[c], 'important');
            }
        }

        // 服务状态注入到启用复选框行，其余部分组合返回
        return m.render().then(function(formEl) {
            // LuCI Flag 渲染结构：.cbi-value-field > input[hidden] + input[checkbox] + label + ...
            // 将 serviceStatusView 插入到 label（视觉开关）之后
            var checkbox = formEl.querySelector('input[type="checkbox"]');
            if (checkbox) {
                var toggleLabel = checkbox.nextElementSibling;
                if (toggleLabel && toggleLabel.tagName === 'LABEL') {
                    toggleLabel.parentNode.insertBefore(serviceStatusView, toggleLabel.nextSibling);
                } else {
                    checkbox.parentNode.insertBefore(serviceStatusView, checkbox.nextSibling);
                }
            }

            // 列宽必须等表格真正排版之后再量：本函数运行时 formEl 还没插进文档，
            // clientWidth 是 0。
            var tbl = formEl.querySelector('#cbi-netcontrol-device table');

            // 首帧兜底：用 rAF 轮询到表格真的有宽度为止。observe() 一个尚未插入
            // 文档的元素时，ResizeObserver 的初始回调不保证发生。
            var tries = 0;
            (function waitLayout() {
                var t = formEl.querySelector('#cbi-netcontrol-device table');
                if (t && (t.clientWidth || t.offsetWidth)) {
                    applyColumnWidths(formEl, true);
                    return;
                }
                if (++tries < 120) requestAnimationFrame(waitLayout);   // 最多等约 2 秒
            })();

            // 之后容器变宽变窄（改窗口、折叠侧栏、开关 DevTools）由它兜住
            if (tbl && window.ResizeObserver)
                new ResizeObserver(function() { applyColumnWidths(formEl, true); }).observe(tbl);
            else
                window.addEventListener('resize', function() { applyColumnWidths(formEl, true); });

            // 点「添加」「删除」后 LuCI 会重建表格行，行内样式随之丢失，这里补写回去
            new MutationObserver(function() { applyColumnWidths(formEl, false); })
                .observe(formEl, { childList: true, subtree: true });

            var parts = [E('style', [tableCss]), formEl, deviceStatusSection];
            if (randomMacSection) parts.push(randomMacSection);
            return E('div', {}, parts);
        });
    }
});
