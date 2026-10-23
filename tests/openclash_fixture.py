#!/usr/bin/env python3
"""Materialize the complete reviewed patch inputs for isolated plugin tests."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/openclash/0.48.002"
SOURCES = {
    "openclash.init": "root/etc/init.d/openclash",
    "YAML.rb": "root/usr/share/openclash/YAML.rb",
    "switch_dashboard.htm": "luasrc/view/openclash/switch_dashboard.htm",
    "controller-openclash.lua": "luasrc/controller/openclash.lua",
    "config-subscribe-edit.lua": "luasrc/model/cbi/openclash/config-subscribe-edit.lua",
    "luci-openclash.lua": "luasrc/openclash.lua",
    "config_edit.js": "root/www/luci-static/resources/openclash/js/config_edit.js",
}


def make_package(destination):
    for fixture, target in SOURCES.items():
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / fixture, path)
    target = destination / "root/usr/share/openclash/openclash_curl.sh"
    shutil.copyfile(ROOT / "tests/fixtures/plugin-runtime/openclash_curl.sh", target)


if __name__ == "__main__":
    make_package(Path(sys.argv[1]))
