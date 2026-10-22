#!/bin/sh
# update.lua activates every rule type through its checked lifecycle reload.
# Abort this run on activation failure before subscription changes can restart.
/usr/bin/lua /usr/share/shadowsocksr/update.lua || exit $?
sleep 2s
/usr/bin/lua /usr/share/shadowsocksr/subscribe.lua
exit $?
