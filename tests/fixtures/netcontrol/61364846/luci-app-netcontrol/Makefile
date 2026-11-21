#
# Copyright (C) 2026 rule2c <rule2c@gmail.com>
#
# This is free software, licensed under the GNU General Public License v2.
# See ../LICENSE for more information.
#

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-netcontrol

PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_MAINTAINER:=rule2c <rule2c@gmail.com>
PKG_LICENSE:=GPL-2.0

LUCI_TITLE:=Per-device internet access scheduling and quotas
LUCI_DESCRIPTION:=Restrict LAN devices by time window, cumulative online quota, or both. \
Targets may be given as a single IP, a CIDR range, an IP range, a MAC address or an IPv6 \
address. Enforced with nftables sets; quotas only advance while the device is actually \
sending traffic.
LUCI_DEPENDS:=+nftables +conntrack
LUCI_PKGARCH:=all

define Build/Compile
endef

# 刷新 LuCI 的菜单/资源缓存，否则新装后侧栏可能不出现本插件
define Package/$(PKG_NAME)/postinst
#!/bin/sh
rm -f /tmp/luci-indexcache /tmp/luci-modulecache/* 2>/dev/null
exit 0
endef

define Package/$(PKG_NAME)/conffiles
/etc/config/netcontrol
endef

include $(TOPDIR)/feeds/luci/luci.mk

# luci.mk 末尾自己会调 BuildPackage，这里不能再调一次。
# 保留下面这行是因为部分打包脚本靠 grep "BuildPackage" 识别包 Makefile。
# call BuildPackage - OpenWrt buildroot signature
