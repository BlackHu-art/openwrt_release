from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str) -> None:
    text = read(path)
    assert needle in text, f"{path}: missing {needle!r}"


def reject(path: str, needle: str) -> None:
    text = read(path)
    assert needle not in text, f"{path}: retained forbidden {needle!r}"


def load_workflow(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    assert isinstance(data, dict), f"{path}: workflow root is not a mapping"
    return data


required_paths = [
    "CLEANUP_GUIDE.md",
    "tu.png",
    "wrt_core/deconfig/banner",
    "wrt_core/deconfig/fragments/proxy.config",
    "wrt_core/deconfig/fragments/nss.config",
    "wrt_core/compilecfg/supergateway_s20m_immwrt.ini",
    "wrt_core/deconfig/supergateway_s20m_immwrt.config",
    "wrt_core/deconfig/fragments/docker_deps.config",
    "wrt_core/modules/banner.sh",
    ".github/workflows/build_wrt.yml",
    ".github/workflows/release_wrt.yml",
    ".github/workflows/release_wrt_all.yml",
]
for item in required_paths:
    assert (ROOT / item).exists(), f"missing required path: {item}"

s20m_config = "wrt_core/deconfig/supergateway_s20m_immwrt.config"
# The selected source branch defines S20M under mediatek/filogic, not mt7986.
require(s20m_config, "CONFIG_TARGET_mediatek_filogic=y")
require(s20m_config, "CONFIG_TARGET_DEVICE_mediatek_filogic_DEVICE_supergateway_s20m=y")
reject(s20m_config, "CONFIG_TARGET_mediatek_mt7986=y")

base = "wrt_core/deconfig/compile_base.config"
for setting in [
    "CONFIG_PACKAGE_automount=y",
    "CONFIG_PACKAGE_easytier=n",
    "CONFIG_PACKAGE_luci-app-easytier=n",
    "CONFIG_PACKAGE_luci-app-lucky=n",
    "CONFIG_PACKAGE_luci-app-mosdns=n",
    "CONFIG_PACKAGE_luci-app-pbr=n",
    "CONFIG_PACKAGE_luci-app-wol=n",
    "CONFIG_PACKAGE_luci-theme-argon=y",
    "CONFIG_PACKAGE_luci-app-argon-config=y",
    "CONFIG_PACKAGE_luci-theme-aurora=y",
    "CONFIG_PACKAGE_luci-app-aurora-config=y",
]:
    require(base, setting)

for config in (ROOT / "wrt_core/deconfig").glob("*.config"):
    assert "cupsd" not in config.read_text(encoding="utf-8"), (
        f"{config}: CUPS remains enabled"
    )

for config in [
    "wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config",
    "wrt_core/deconfig/jdcloud_ipq60xx_libwrt.config",
    "wrt_core/deconfig/link_nn6000v2_immwrt.config",
]:
    require(config, "CONFIG_PACKAGE_luci-app-openclash=y")
    require(config, "CONFIG_PACKAGE_luci-app-homeproxy=y")

require(
    "wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config",
    "CONFIG_PACKAGE_luci-app-passwall2=y",
)
require(
    "wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config",
    "CONFIG_PACKAGE_luci-app-ssr-plus=y",
)
for model in ["jdcloud_ipq60xx_immwrt", "jdcloud_ipq60xx_libwrt", "jdcloud_ax6000_immwrt"]:
    config = f"wrt_core/deconfig/{model}.config"
    for package in [
        "luci-app-dockerman", "luci-i18n-dockerman-zh-cn", "luci-lib-docker",
        "docker", "dockerd", "docker-compose", "containerd", "runc",
    ]:
        require(config, f"CONFIG_PACKAGE_{package}=n")
        reject(config, f" {package}")
    reject(f"wrt_core/compilecfg/{model}.ini", "docker_deps")

require(
    "wrt_core/modules/package_source_updates.sh",
    "https://github.com/jerrykuku/luci-theme-argon.git",
)
require(
    "wrt_core/modules/package_source_updates.sh",
    "https://github.com/jerrykuku/luci-app-argon-config.git",
)
require(
    "wrt_core/modules/package_source_updates.sh",
    "https://github.com/eamonxg/luci-theme-aurora.git",
)
require(
    "wrt_core/modules/package_source_updates.sh",
    "https://github.com/eamonxg/luci-app-aurora-config.git",
)
require("wrt_core/update.sh", 'LAN_ADDR="10.0.0.1"')
for call in ["update_argon_config", "update_aurora", "update_aurora_config"]:
    require("wrt_core/update.sh", call)

assert not (ROOT / "wrt_core/modules/cups.sh").exists(), (
    "CUPS module must remain removed"
)
reject("wrt_core/update.sh", "fix_cups_libcups_avahi_depends")
reject("wrt_core/modules/custom_feed.sh", "luci-app-cupsd")

require("build.sh", 'source "$BASE_PATH/modules/banner.sh"')
require(
    "build.sh",
    'install_custom_banner "$BASE_PATH/deconfig/banner" "$BASE_PATH/../$BUILD_DIR"',
)
require(
    "build.sh",
    '"$BASE_PATH/update.sh" "$REPO_URL" "$REPO_BRANCH" "$BUILD_DIR" "$COMMIT_HASH" "$DOCKER_STACK_SELECTED"',
)
require(
    "wrt_core/update.sh",
    'docker_stack_sync_nftables_compat_if_selected "$DOCKER_STACK_SELECTED" "$BUILD_DIR" "0"',
)
require("wrt_core/modules/target_fixes.sh", "991_custom_settings")

for workflow_path in [
    ".github/workflows/build_wrt.yml",
    ".github/workflows/release_wrt.yml",
    ".github/workflows/release_wrt_all.yml",
]:
    workflow = load_workflow(workflow_path)
    require(workflow_path, "- supergateway_s20m_immwrt")
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict), f"{workflow_path}: invalid on section"
    assert "push" not in trigger and "schedule" not in trigger, (
        f"{workflow_path}: automatic trigger enabled"
    )

release = read(".github/workflows/release_wrt.yml")
assert "${{ inputs.model }}_${{ env.BUILD_DATE }}" in release
assert "KEEP_RELEASE=2" in release
assert "KMOD_ARCHIVE" in release
assert "workflow_call:" in release

batch = read(".github/workflows/release_wrt_all.yml")
assert "uses: ./.github/workflows/release_wrt.yml" in batch
assert "matrix.model" in batch

VIKINGYFY_REPO_URL = "https://github.com/VIKINGYFY/immortalwrt.git"
VIKINGYFY_PIN = "3fd1e27a511851b41cf082b067b60099e8e026c4"
vikingyfy_ipq60xx = {
    "jdcloud_ipq60xx_immwrt",
    "link_nn6000v2_immwrt",
    "qihoo_360v6_immwrt",
    "redmi_ax5_immwrt",
    "zn_m2_immwrt",
}
vikingyfy_pins = {}
for config in (ROOT / "wrt_core/compilecfg").glob("*.ini"):
    settings = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            settings[key] = value
    if (
        settings.get("REPO_URL") == VIKINGYFY_REPO_URL
        and settings.get("REPO_BRANCH") == "main"
        and "COMMIT_HASH" in settings
    ):
        vikingyfy_pins[config.stem] = settings["COMMIT_HASH"]

assert set(vikingyfy_pins) == vikingyfy_ipq60xx, (
    f"unexpected VIKINGYFY/main pinned devices: {sorted(vikingyfy_pins)}"
)
assert all(value == VIKINGYFY_PIN for value in vikingyfy_pins.values()), (
    f"unexpected VIKINGYFY/main pin values: {vikingyfy_pins}"
)

print("upstream synchronization invariants: PASS")
