// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2026 rule2c <rule2c@gmail.com>
 */
'use strict';
'require dom';
'require fs';
'require poll';
'require view';

var LOG_FILE = '/var/log/netcontrol.log';
var CALL_WRAPPER = '/usr/libexec/netcontrol-call';

// 守护进程与防火墙脚本写出的行格式：[YYYY-MM-DD HH:MM:SS] TAG: 正文
var ENTRY_RE = /^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\]\s+([A-Z]+-[A-Z]+):\s*([\s\S]*)$/;

// 正文关键词 → 强调色。与 netcontrol-log realtime 的终端配色保持一致，
// 两个界面看同一份日志时颜色含义相同。
var ACCENTS = [
	{ level: 'bad',   words: ['失败', '错误'] },
	{ level: 'good',  words: ['已恢复', '开始累计'] },
	{ level: 'warn',  words: ['已限制', '已重置', '暂停累计'] }
];

function accentOf(text) {
	for (var i = 0; i < ACCENTS.length; i++)
		for (var j = 0; j < ACCENTS[i].words.length; j++)
			if (text.indexOf(ACCENTS[i].words[j]) >= 0)
				return ACCENTS[i].level;
	return '';
}

var STYLE = `
	.nc-log-bar {
		display: flex;
		align-items: center;
		gap: .75rem;
		flex-wrap: wrap;
		margin-bottom: .6rem;
	}
	.nc-log-count {
		font-size: .85em;
		opacity: .7;
	}
	.nc-log-view {
		max-height: 70vh;
		overflow-y: auto;
		border: 1px solid rgba(128,128,128,.35);
		border-radius: 4px;
		padding: .3rem 0;
	}
	.nc-entry {
		display: grid;
		grid-template-columns: 6.2rem 5.6rem 1fr;
		gap: .5rem;
		align-items: baseline;
		padding: .18rem .6rem;
		font-family: ui-monospace, Consolas, monospace;
		font-size: 12px;
		line-height: 1.5;
		border-left: 3px solid transparent;
	}
	.nc-entry:nth-child(odd) { background: rgba(128,128,128,.06); }
	.nc-entry.bad  { border-left-color: #d9534f; }
	.nc-entry.good { border-left-color: #5cb85c; }
	.nc-entry.warn { border-left-color: #e0a800; }
	.nc-time { opacity: .65; white-space: nowrap; }
	.nc-tag  { opacity: .55; white-space: nowrap; font-size: 11px; }
	.nc-text { word-break: break-word; }
	.nc-entry.bad  .nc-text { color: #d9534f; }
	.nc-entry.good .nc-text { color: #3d8b40; }
	.nc-entry.warn .nc-text { color: #a37500; }
	/* 解析不出格式的行（比如手工写进去的内容）整行照原样显示 */
	.nc-raw { grid-column: 1 / -1; opacity: .8; }
	.nc-placeholder {
		padding: 1.2rem .6rem;
		text-align: center;
		opacity: .6;
	}
	/* 同一天的多条记录只在第一条显示日期，减少视觉噪音 */
	.nc-entry.same-day .nc-date { visibility: hidden; }
`;

return view.extend({
	render: function () {
		var pane = E('div', { 'class': 'nc-log-view' },
			E('div', { 'class': 'nc-placeholder' }, _('Loading...')));
		var counter = E('span', { 'class': 'nc-log-count' }, '');
		// 上次渲染内容的标记，用于跳过无变化的刷新。正文与错误提示分开存。
		var lastText = null, lastNotice = null;

		// 日志以 >> 追加写入，天然按时间有序，倒序显示直接 reverse 即可
		function build(raw) {
			var lines = raw.split('\n');
			var rows = [], prevDate = null;

			for (var i = lines.length - 1; i >= 0; i--) {
				var line = lines[i].trim();
				if (!line) continue;

				var m = ENTRY_RE.exec(line);
				if (!m) {
					rows.push(E('div', { 'class': 'nc-entry' },
						E('span', { 'class': 'nc-raw' }, line)));
					continue;
				}

				var date = m[1], time = m[2], tag = m[3], text = m[4];
				var cls = 'nc-entry' + (accentOf(text) ? ' ' + accentOf(text) : '')
				        + (date === prevDate ? ' same-day' : '');
				prevDate = date;

				rows.push(E('div', { 'class': cls, 'title': date + ' ' + time }, [
					E('span', { 'class': 'nc-time' }, [
						E('span', { 'class': 'nc-date' }, date.slice(5) + ' '), time
					]),
					E('span', { 'class': 'nc-tag' }, tag),
					E('span', { 'class': 'nc-text' }, text)
				]));
			}

			counter.textContent = rows.length ? _('%d entries').format(rows.length) : '';
			return rows.length ? rows
			                   : [E('div', { 'class': 'nc-placeholder' }, _('Log is empty.'))];
		}

		function showNotice(msg) {
			lastText = null;
			counter.textContent = '';
			dom.content(pane, E('div', { 'class': 'nc-placeholder' }, msg));
		}

		// 新记录出现在顶部。已经往下翻的用户按新增高度补偿 scrollTop，不被拽走。
		function render(raw) {
			var atTop = pane.scrollTop <= 2;
			var before = pane.scrollHeight;
			dom.content(pane, build(raw));
			pane.scrollTop = atTop ? 0 : pane.scrollTop + (pane.scrollHeight - before);
		}

		var clearBtn = E('button', {
			'class': 'cbi-button cbi-button-remove',
			'click': function (ev) {
				ev.preventDefault();
				var btn = ev.currentTarget, label = btn.textContent;
				var restore = function () { btn.disabled = false; btn.textContent = label; };
				btn.disabled = true;
				btn.textContent = _('Clearing...');
				fs.exec_direct(CALL_WRAPPER, ['clear_log']).then(function () {
					lastNotice = _('Log is empty.');
					showNotice(lastNotice);
					restore();
				}).catch(function (err) {
					lastNotice = _('Failed to read log: %s').format(err);
					showNotice(lastNotice);
					restore();
				});
			}
		}, _('Clear Logs'));

		poll.add(function () {
			return fs.read_direct(LOG_FILE, 'text').then(function (raw) {
				raw = (raw || '').replace(/\s+$/, '');
				if (raw) {
					if (raw === lastText) return;      // 内容没变就不重建 DOM
					lastText = raw; lastNotice = null;
					render(raw);
				} else if (lastNotice !== _('Log is empty.')) {
					lastNotice = _('Log is empty.');
					showNotice(lastNotice);
				}
			}).catch(function (err) {
				var msg = String(err).indexOf('NotFoundError') >= 0
					? _('Log file does not exist.')
					: _('Failed to read log: %s').format(err);
				if (msg === lastNotice) return;
				lastNotice = msg;
				showNotice(msg);
			});
		});
		poll.start();

		return E('div', { 'class': 'cbi-map' }, [
			E('style', [STYLE]),
			E('div', { 'class': 'cbi-section' }, [
				E('div', { 'class': 'nc-log-bar' }, [clearBtn, counter]),
				pane,
				E('div', { 'class': 'nc-log-count', 'style': 'margin-top:.5rem' },
					_('Auto-refreshes every 5 seconds. Newest entries first.'))
			])
		]);
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
