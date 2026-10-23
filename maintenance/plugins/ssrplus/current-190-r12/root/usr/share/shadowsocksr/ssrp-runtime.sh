#!/bin/sh
# Local SSR compatibility runtime. POSIX/BusyBox ash; no router settings changed.

ssrp_run_locked() (
	mkdir -p "${LOCK_FILE%/*}" || exit 1
	# Never unlink this file: waiters must all lock the same inode.
	exec 9>>"$LOCK_FILE" || exit 1
	flock -w 30 -x 9 || exit 1
	# The process doing the work owns the lock. Close FD9 only at daemon
	# launch boundaries, so a killed supervisor cannot leave an unlocked worker.
	trap 'ssrp_lifecycle_exit "$?"' EXIT
	trap 'exit 129' HUP
	trap 'exit 130' INT
	trap 'exit 143' TERM
	"$@"
)

ssrp_dnsmasq() {
	/etc/init.d/dnsmasq "$@"
}

ssrp_filter() {
	# grep's empty result is valid; input/read failures must abort generation.
	grep "$@" || [ "$?" -eq 1 ]
}

ssrp_emergency_dns_restore() {
	local result=0
	# A failed firewall cleanup must not bypass the DNS recovery attempt.
	# Handle the old UCI takeover marker when upgrading an existing install.
	if [ "$(uci -q get 'dhcp.@dnsmasq[0]._unused_ssrp_changed' 2>/dev/null)" = 1 ]; then
		uci -q del 'dhcp.@dnsmasq[0].noresolv'
		uci -q del_list "dhcp.@dnsmasq[0].server=127.0.0.1#$china_dns_port"
		uci -q rename 'dhcp.@dnsmasq[0]._orig_noresolv=noresolv'
		uci -q rename 'dhcp.@dnsmasq[0]._orig_server=server'
		uci -q del 'dhcp.@dnsmasq[0]._unused_ssrp_changed'
		uci -q commit dhcp || result=1
	fi
	rm -f "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf" || result=1
	ssrp_dnsmasq restart || result=1
	return "$result"
}

ssrp_lifecycle_exit() {
	local status=$1
	ssrp_dns_abort
	if [ "$status" -ne 0 ] && [ "${SSRP_REPLACING:-0}" = 1 ]; then
		# This is cleanup, not rollback of a previously running proxy core.
		SSRP_KEEP_DNS=0
		if ! ssrp_stop; then
			printf '%s\n' 'SSR replacement and cleanup failed' >&2
			ssrp_emergency_dns_restore || printf '%s\n' 'SSR emergency DNS restoration failed' >&2
		fi
		printf '%s\n' 'SSR replacement failed; attempted SSR cleanup and default DNS restoration' >&2
	fi
	return "$status"
}

ssrp_service_start() {
	if [ "${SSRP_PREPARE_ONLY:-0}" = 1 ]; then
		[ -x "$1" ] || _exit 1
		return 0
	fi
	service_start "$@" 9>&-
}

ssrp_valid_ip() {
	awk 'function v4(v, a,n,i) {
		n=split(v,a,"."); if(n!=4) return 0;
		for(i=1;i<=4;i++) if(a[i]!~/^[0-9]+$/ || length(a[i])>3 || a[i]+0>255) return 0;
		return 1;
	} BEGIN {
		v=ARGV[1]; if(index(v,":")==0) exit !v4(v);
		if(index(v,".")) { n=split(v,a,":"); if(!v4(a[n])) exit 1; sub(/[^:]*$/,"0:0",v); }
		if(v!~/^[0-9a-fA-F:]+$/ || v~/:::/ || length(v)>39) exit 1;
		compressed=index(v,"::"); rest=v; if(compressed) { sub(/::/,"",rest); if(index(rest,"::")) exit 1; }
		if(v~/^:[^:]/ || v~/[^:]:$/) exit 1;
		if(!compressed && (v~/^:/ || v~/:$/)) exit 1;
		n=split(v,a,":"); count=0;
		for(i=1;i<=n;i++) if(length(a[i])) { if(length(a[i])>4) exit 1; count++; }
		exit !(compressed ? count<8 : count==8);
	}' "$1"
}

ssrp_dns_begin() {
	[ -z "${SSRP_DNS_STAGE:-}" ] || return 1
	mkdir -p "$DNSMASQ_CONF_DIR" || return 1
	SSRP_DNS_ACTIVE="$TMP_DNSMASQ_PATH"
	SSRP_DNS_STAGE=$(mktemp -d "$DNSMASQ_CONF_DIR/.ssrplus-dns.XXXXXX") || return 1
	TMP_DNSMASQ_PATH="$SSRP_DNS_STAGE"
}

ssrp_dns_abort() {
	if [ -n "${SSRP_DNS_STAGE:-}" ]; then
		case "$SSRP_DNS_STAGE" in
			"$DNSMASQ_CONF_DIR"/.ssrplus-dns.*) rm -rf "$SSRP_DNS_STAGE" ;;
		esac
		TMP_DNSMASQ_PATH="$SSRP_DNS_ACTIVE"
		SSRP_DNS_STAGE=
	fi
}

ssrp_dns_validate() {
	local fragment bundle
	[ -n "${SSRP_DNS_STAGE:-}" ] || return 1
	bundle="$SSRP_DNS_STAGE/.bundle"
	: > "$bundle" || return 1
	for fragment in "$SSRP_DNS_STAGE"/*.conf; do
		[ -f "$fragment" ] || continue
		cat "$fragment" >> "$bundle" || return 1
		printf '\n' >> "$bundle" || return 1
	done
	# Use the installed binary: unsupported ipset directives must be rejected.
	if ! dnsmasq --test --conf-file="$bundle" >"$SSRP_DNS_STAGE/.validation" 2>&1; then
		cat "$SSRP_DNS_STAGE/.validation" >&2
		return 1
	fi
	return 0
}

ssrp_dns_publish() {
	local bundle temporary
	ssrp_dns_validate || return 1
	bundle="$SSRP_DNS_STAGE/.bundle"
	# One rename is the entire publication. A reader opens either the old
	# complete configuration or the new one; no nested include is required by
	# dnsmasq's ujail, and no old configuration is removed on failure.
	temporary=$(mktemp "$DNSMASQ_CONF_DIR/.ssrplus-config.XXXXXX") || return 1
	if ! cp "$bundle" "$temporary" || ! chmod 644 "$temporary" ||
		! mv -f "$temporary" "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf"; then
		rm -f "$temporary"
		return 1
	fi
	ssrp_dns_abort
}

ssrp_has_processes() {
	# Search command lines, not executable names shared with other plugins.
	$PS -w | grep -F "$TMP_PATH/" | grep -v 'grep' >/dev/null 2>&1
}

ssrp_start_locked() {
	if ssrp_has_processes; then
		ssrp_restart_locked "$@"
	else
		if command -v ssrp_preflight >/dev/null 2>&1; then
			ssrp_preflight || return 1
		fi
		SSRP_REPLACING=1
		ssrp_start "$@"
	fi
}

ssrp_restart_locked() {
	local result
	if command -v ssrp_preflight >/dev/null 2>&1; then
		ssrp_preflight || return 1
	fi
	SSRP_REPLACING=1
	SSRP_KEEP_DNS=1
	ssrp_stop "$@" || return 1
	SSRP_KEEP_DNS=0
	ssrp_start "$@"
	result=$?
	return "$result"
}
