# Upstream Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate `ZqinKing/wrt_release@4bf1cc018f8f1f08a0e1564f1cd16a38ccb004bc` into the downstream repository while preserving its firmware choices, plugins, themes, device configurations, workflows, and banner behavior.

**Architecture:** Connect the unrelated histories with an `ours` merge, adopt the upstream file tree in a separate commit, and then port downstream behavior into the upstream modular layout. Verification is encoded in cross-platform Python and shell tests before the branch is fast-forwarded into `master` and pushed only to `origin`.

**Tech Stack:** Git, Bash, Python 3 with PyYAML, GitHub Actions YAML, OpenWrt Kconfig fragments.

## Global Constraints

- Upstream `https://github.com/ZqinKing/wrt_release.git` is read-only and must never receive a push.
- Push only to `origin`, `https://github.com/BlackHu-art/openwrt_release.git`.
- Preserve `backup/pre-upstream-sync-20260809` at `06803a6197f98b800a0f7f4a258321caef2edcda`.
- Work on `sync/upstream-20260809`; do not rewrite history or force-push.
- Preserve downstream firmware/device selections, Aurora and Argon sources, package exclusions, Docker/LiBwrt choices, release behavior, `CLEANUP_GUIDE.md`, `tu.png`, and custom banner behavior.
- Use upstream modules and configuration fragments instead of restoring obsolete monolithic implementations.
- Keep GitHub Actions builds manually triggered after the push.
- A full firmware compilation is not part of local verification.

---

## File Map

- `build.sh`: upstream build entry point; sources and invokes banner installation.
- `wrt_core/modules/banner.sh`: isolated custom-banner installer.
- `wrt_core/modules/package_source_updates.sh`: Argon, Argon config, Aurora, and Aurora config source synchronization.
- `wrt_core/update.sh`: static module orchestration, LAN address, and theme update calls.
- `wrt_core/modules/custom_feed.sh`: custom-feed package list without CUPS.
- `wrt_core/modules/feed_source_fixes.sh`: upstream feed cleanup without CUPS handling.
- `wrt_core/deconfig/compile_base.config`: downstream global package choices.
- `wrt_core/deconfig/*.config`: device-specific package choices and CUPS removal.
- `.github/workflows/release_wrt.yml`: manual/reusable single-device release workflow.
- `.github/workflows/release_wrt_all.yml`: manual matrix caller for all devices.
- `.github/workflows/build_wrt.yml`: upstream manual build workflow retained unchanged except where verification exposes a downstream invariant.
- `tests/verify_upstream_sync.py`: static project, configuration, and workflow invariants.
- `tests/test_banner.sh`: functional banner-copy and missing-source tests.

---

### Task 1: Connect histories and adopt the upstream tree

**Files:**
- Replace from upstream: repository tracked tree
- Preserve from downstream: `docs/superpowers/**`, `CLEANUP_GUIDE.md`, `tu.png`, `wrt_core/deconfig/banner`, `.github/workflows/release_wrt_all.yml`

**Interfaces:**
- Consumes: local commit `f4bcc7c`, backup ref `backup/pre-upstream-sync-20260809`, fetched `upstream/main`.
- Produces: a branch where `upstream/main` is an ancestor and the working tree uses the upstream architecture.

- [ ] **Step 1: Verify the protected starting state**

```powershell
git status --short --branch
git rev-parse backup/pre-upstream-sync-20260809
git rev-parse upstream/main
```

Expected: clean `sync/upstream-20260809`; backup resolves to `06803a6197f98b800a0f7f4a258321caef2edcda`; upstream resolves to `4bf1cc018f8f1f08a0e1564f1cd16a38ccb004bc`.

- [ ] **Step 2: Configure a fetchable but non-pushable upstream remote**

```powershell
git remote add upstream https://github.com/ZqinKing/wrt_release.git
git remote set-url --push upstream DISABLED
git fetch --no-tags upstream main
git remote -v
```

Expected: upstream fetch URL is GitHub and upstream push URL is `DISABLED`; origin remains `BlackHu-art/openwrt_release`.

- [ ] **Step 3: Connect the unrelated histories without changing the tree**

```powershell
git merge --allow-unrelated-histories -s ours upstream/main -m "chore: connect upstream history"
git merge-base --is-ancestor upstream/main HEAD
```

Expected: merge succeeds and the ancestry check exits 0.

- [ ] **Step 4: Replace the tracked tree with upstream while restoring downstream-owned assets**

```powershell
$downstreamMerge = git rev-parse HEAD
git restore --source=upstream/main --staged --worktree -- :/
git restore --source=$downstreamMerge --staged --worktree -- docs/superpowers CLEANUP_GUIDE.md tu.png wrt_core/deconfig/banner .github/workflows/release_wrt_all.yml
git status --short
```

Expected: upstream additions such as `wrt_core/modules/custom_feed.sh` and configuration fragments are staged; the five downstream paths still exist.

- [ ] **Step 5: Verify the adopted architecture**

```powershell
Test-Path wrt_core/modules/custom_feed.sh
Test-Path wrt_core/deconfig/fragments/proxy.config
Test-Path wrt_core/build_container.sh
git diff --cached --check
```

Expected: all three path checks are `True`; diff check has no output.

- [ ] **Step 6: Commit the upstream tree adoption**

```powershell
git commit -m "chore: adopt upstream project structure"
```

---

### Task 2: Add executable downstream preservation tests

**Files:**
- Create: `tests/verify_upstream_sync.py`
- Create: `tests/test_banner.sh`

**Interfaces:**
- Consumes: repository paths and YAML workflows.
- Produces: `python tests/verify_upstream_sync.py` and `bash tests/test_banner.sh` verification commands.

- [ ] **Step 1: Create the static invariant test**

Create `tests/verify_upstream_sync.py` with these assertions:

```python
from pathlib import Path
import re
import sys
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
    "wrt_core/deconfig/fragments/docker_deps.config",
    "wrt_core/modules/banner.sh",
    ".github/workflows/build_wrt.yml",
    ".github/workflows/release_wrt.yml",
    ".github/workflows/release_wrt_all.yml",
]
for item in required_paths:
    assert (ROOT / item).exists(), f"missing required path: {item}"

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
    assert "cupsd" not in config.read_text(encoding="utf-8"), f"{config}: CUPS remains enabled"

for config in [
    "wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config",
    "wrt_core/deconfig/jdcloud_ipq60xx_libwrt.config",
    "wrt_core/deconfig/link_nn6000v2_immwrt.config",
]:
    require(config, "CONFIG_PACKAGE_luci-app-openclash=y")
    require(config, "CONFIG_PACKAGE_luci-app-homeproxy=y")

require("wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config", "CONFIG_PACKAGE_luci-app-passwall2=y")
require("wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config", "CONFIG_PACKAGE_luci-app-ssr-plus=y")
require("wrt_core/deconfig/jdcloud_ipq60xx_libwrt.config", "luci-app-dockerman luci-i18n-dockerman-zh-cn")

require("wrt_core/modules/package_source_updates.sh", "https://github.com/jerrykuku/luci-theme-argon.git")
require("wrt_core/modules/package_source_updates.sh", "https://github.com/jerrykuku/luci-app-argon-config.git")
require("wrt_core/modules/package_source_updates.sh", "https://github.com/eamonxg/luci-theme-aurora.git")
require("wrt_core/modules/package_source_updates.sh", "https://github.com/eamonxg/luci-app-aurora-config.git")
require("wrt_core/update.sh", 'LAN_ADDR="10.0.0.1"')
for call in ["update_argon_config", "update_aurora", "update_aurora_config"]:
    require("wrt_core/update.sh", call)

assert not (ROOT / "wrt_core/modules/cups.sh").exists(), "CUPS module must remain removed"
reject("wrt_core/update.sh", "fix_cups_libcups_avahi_depends")
reject("wrt_core/modules/custom_feed.sh", "luci-app-cupsd")

require("build.sh", 'source "$BASE_PATH/modules/banner.sh"')
require("build.sh", 'install_custom_banner "$BASE_PATH/deconfig/banner" "$BASE_PATH/../$BUILD_DIR"')
require("wrt_core/modules/target_fixes.sh", "991_custom_settings")

for workflow_path in [
    ".github/workflows/build_wrt.yml",
    ".github/workflows/release_wrt.yml",
    ".github/workflows/release_wrt_all.yml",
]:
    workflow = load_workflow(workflow_path)
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict), f"{workflow_path}: invalid on section"
    assert "push" not in trigger and "schedule" not in trigger, f"{workflow_path}: automatic trigger enabled"

release = read(".github/workflows/release_wrt.yml")
assert "${{ inputs.model }}_${{ env.BUILD_DATE }}" in release
assert "KEEP_RELEASE=2" in release
assert "KMOD_ARCHIVE" in release
assert "workflow_call:" in release

batch = read(".github/workflows/release_wrt_all.yml")
assert "uses: ./.github/workflows/release_wrt.yml" in batch
assert "matrix.model" in batch

print("upstream synchronization invariants: PASS")
```

- [ ] **Step 2: Create the banner behavior test**

Create `tests/test_banner.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/banner.sh"

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT

source_banner="$test_root/custom-banner"
build_root="$test_root/build"
target_banner="$build_root/package/base-files/files/etc/banner"
printf 'Frankie downstream banner\n' > "$source_banner"

install_custom_banner "$source_banner" "$build_root"
cmp "$source_banner" "$target_banner"

printf 'OpenWrt default banner\n' > "$target_banner"
install_custom_banner "$test_root/missing-banner" "$build_root"
grep -Fx 'OpenWrt default banner' "$target_banner"

echo "banner behavior: PASS"
```

- [ ] **Step 3: Run the tests and confirm they fail for missing downstream behavior**

```powershell
python tests/verify_upstream_sync.py
& 'C:\Program Files\Git\bin\bash.exe' tests/test_banner.sh
```

Expected: the Python test fails first on missing `wrt_core/modules/banner.sh`; the banner test fails because that module does not exist.

- [ ] **Step 4: Commit the failing tests**

```powershell
git add tests/verify_upstream_sync.py tests/test_banner.sh
git commit -m "test: codify downstream sync invariants"
```

---

### Task 3: Migrate package, theme, and device configuration behavior

**Files:**
- Modify: `wrt_core/deconfig/compile_base.config`
- Modify: `wrt_core/deconfig/jdcloud_ipq60xx_immwrt.config`
- Modify: `wrt_core/deconfig/jdcloud_ipq60xx_libwrt.config`
- Modify: `wrt_core/deconfig/link_nn6000v2_immwrt.config`
- Modify: other `wrt_core/deconfig/*.config` files containing `cupsd`
- Modify: `wrt_core/modules/package_source_updates.sh`
- Modify: `wrt_core/modules/custom_feed.sh`
- Modify: `wrt_core/modules/feed_source_fixes.sh`
- Modify: `wrt_core/update.sh`
- Delete: `wrt_core/modules/cups.sh`

**Interfaces:**
- Consumes: upstream static module stages and Kconfig fragment order.
- Produces: downstream package/theme choices expressed in the upstream layout.

- [ ] **Step 1: Restore downstream global Kconfig choices**

Apply these exact settings in `wrt_core/deconfig/compile_base.config`:

```text
CONFIG_PACKAGE_automount=y
CONFIG_PACKAGE_easytier=n
CONFIG_PACKAGE_luci-app-easytier=n
CONFIG_PACKAGE_luci-app-lucky=n
CONFIG_PACKAGE_luci-app-mosdns=n
CONFIG_PACKAGE_luci-app-pbr=n
CONFIG_PACKAGE_luci-app-wol=n
CONFIG_PACKAGE_luci-theme-argon=y
CONFIG_PACKAGE_luci-app-argon-config=y
CONFIG_PACKAGE_luci-theme-aurora=y
CONFIG_PACKAGE_luci-app-aurora-config=y
```

- [ ] **Step 2: Restore downstream device selections and remove CUPS from every device**

For both IPQ60xx configs, remove `luci-app-cupsd` from per-device package strings, retain Dockerman for CS-02 and CS-07, keep upstream `luci-app-emmc-health`, and append:

```text
CONFIG_PACKAGE_luci-app-partexp=y
CONFIG_PACKAGE_luci-app-statistics=y
CONFIG_PACKAGE_luci-app-wifischedule=y
CONFIG_PACKAGE_luci-app-openclash=y
CONFIG_PACKAGE_luci-app-homeproxy=y
```

Additionally append to `jdcloud_ipq60xx_immwrt.config`:

```text
CONFIG_PACKAGE_luci-app-passwall2=y
CONFIG_PACKAGE_luci-app-ssr-plus=y
CONFIG_PACKAGE_luci-app-sqm=n
CONFIG_PACKAGE_luci-app-vlmcsd=n
```

Append the shared five selections and explicit SQM/VLMCSd disables to `link_nn6000v2_immwrt.config`, and remove every remaining `cupsd` selection from all device configs.

- [ ] **Step 3: Port Aurora and Argon source updates into the focused module**

In `wrt_core/modules/package_source_updates.sh`, use the existing clone-and-replace pattern to provide these functions and repositories:

```bash
update_argon() {
    replace_luci_source "argon theme" \
        "https://github.com/jerrykuku/luci-theme-argon.git" \
        "$BUILD_DIR/feeds/luci/themes/luci-theme-argon"
}

update_argon_config() {
    replace_luci_source "argon config" \
        "https://github.com/jerrykuku/luci-app-argon-config.git" \
        "$BUILD_DIR/feeds/luci/applications/luci-app-argon-config"
}

update_aurora() {
    replace_luci_source "aurora theme" \
        "https://github.com/eamonxg/luci-theme-aurora.git" \
        "$BUILD_DIR/feeds/luci/themes/luci-theme-aurora"
}

update_aurora_config() {
    replace_luci_source "aurora config" \
        "https://github.com/eamonxg/luci-app-aurora-config.git" \
        "$BUILD_DIR/feeds/luci/applications/luci-app-aurora-config"
}
```

Define `replace_luci_source NAME REPOSITORY DESTINATION` once in the same module. It must clone into `mktemp -d`, remove `.git`, replace the destination, and clean the temporary directory on clone failure.

- [ ] **Step 4: Wire the theme functions and downstream LAN address**

Set and call these exact values in `wrt_core/update.sh`:

```bash
LAN_ADDR="10.0.0.1"

update_argon
update_argon_config
update_aurora
update_aurora_config
```

Keep `THEME_SET="argon"` so the existing Argon default-theme and `990_set_argon_primary` behavior remains unchanged.

- [ ] **Step 5: Remove CUPS from the modular feed pipeline**

Remove `source "$SCRIPT_DIR/modules/cups.sh"` and `fix_cups_libcups_avahi_depends` from `wrt_core/update.sh`; remove CUPS package/directory entries from `custom_feed.sh` and `feed_source_fixes.sh`; delete `wrt_core/modules/cups.sh`.

- [ ] **Step 6: Run the static invariant test**

```powershell
python tests/verify_upstream_sync.py
```

Expected: configuration and theme checks pass; test then fails only because banner/workflow migration is incomplete.

- [ ] **Step 7: Commit package and configuration migration**

```powershell
git add wrt_core/deconfig wrt_core/modules wrt_core/update.sh
git commit -m "feat: migrate downstream firmware customizations"
```

---

### Task 4: Restore custom banner behavior

**Files:**
- Create: `wrt_core/modules/banner.sh`
- Modify: `build.sh`
- Preserve: `wrt_core/deconfig/banner`
- Test: `tests/test_banner.sh`

**Interfaces:**
- Consumes: `install_custom_banner SOURCE BUILD_ROOT`.
- Produces: `<BUILD_ROOT>/package/base-files/files/etc/banner` when the custom source exists.

- [ ] **Step 1: Run the banner test and verify the missing-module failure**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' tests/test_banner.sh
```

Expected: FAIL while sourcing `wrt_core/modules/banner.sh`.

- [ ] **Step 2: Implement the isolated banner installer**

Create `wrt_core/modules/banner.sh`:

```bash
#!/usr/bin/env bash

install_custom_banner() {
    local banner_source=$1
    local build_root=$2
    local banner_target="$build_root/package/base-files/files/etc/banner"

    if [[ ! -f $banner_source ]]; then
        echo "未提供自定义 banner 文件，保持 OpenWrt 默认配置"
        return 0
    fi

    if ! install -Dm644 "$banner_source" "$banner_target"; then
        echo "错误：无法安装自定义 banner 到 $banner_target" >&2
        return 1
    fi

    echo "已应用自定义 banner：$banner_target"
}
```

- [ ] **Step 3: Wire banner installation into the upstream build flow**

After `BASE_PATH` is defined in `build.sh`, add:

```bash
source "$BASE_PATH/modules/banner.sh"
```

Immediately after the `update.sh` call and before `apply_config`, add:

```bash
install_custom_banner "$BASE_PATH/deconfig/banner" "$BASE_PATH/../$BUILD_DIR"
```

- [ ] **Step 4: Run the functional banner test**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' tests/test_banner.sh
```

Expected: prints `banner behavior: PASS` and exits 0.

- [ ] **Step 5: Commit the banner migration**

```powershell
git add build.sh wrt_core/modules/banner.sh wrt_core/deconfig/banner tests/test_banner.sh
git commit -m "feat: preserve custom firmware banner"
```

---

### Task 5: Migrate release workflows

**Files:**
- Modify: `.github/workflows/release_wrt.yml`
- Replace: `.github/workflows/release_wrt_all.yml`
- Test: `tests/verify_upstream_sync.py`

**Interfaces:**
- Consumes: reusable workflow inputs `model`, `add_fragments`, and `remove_fragments`.
- Produces: manual single-device and manual all-device releases using the same implementation.

- [ ] **Step 1: Verify workflow tests fail before migration**

```powershell
python tests/verify_upstream_sync.py
```

Expected: FAIL because `release_wrt.yml` lacks `workflow_call` and the batch workflow does not call it.

- [ ] **Step 2: Make the upstream single-device workflow reusable**

Keep `workflow_dispatch` and add this parallel input contract under `on`:

```yaml
  workflow_call:
    inputs:
      model:
        required: true
        type: string
      add_fragments:
        required: false
        type: string
        default: ""
      remove_fragments:
        required: false
        type: string
        default: ""
```

Retain upstream fragment inputs, disk cleanup, cache keys, KMOD packaging, N1 packaging, and current action versions. Use only explicit permissions:

```yaml
permissions:
  actions: write
  contents: write
```

- [ ] **Step 3: Restore downstream release identity and retention**

Use the downstream tag format:

```yaml
tag_name: ${{ inputs.model }}_${{ env.BUILD_DATE }}
```

Keep the upstream source, kernel, KMOD archive, and plugin details in `release_body.txt`, but set the advertised LAN address to `10.0.0.1`. After publishing, add:

```yaml
      - name: Cleanup Old Releases
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          KEEP_RELEASE=2
          MODEL="${{ inputs.model }}"
          gh release list --limit 200 --json tagName,publishedAt \
            | jq -r ".[] | select(.tagName | startswith(\"${MODEL}_\")) | \"\(.publishedAt) \(.tagName)\"" \
            | sort -r -k1,1 \
            | awk "NR>$KEEP_RELEASE {print \$2}" \
            | while read -r tag; do
                gh release delete "$tag" --yes --cleanup-tag
              done

      - name: Cleanup Old Workflow Runs
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          KEEP_RUNS=10
          gh run list --limit 200 --status completed --json databaseId,createdAt \
            | jq -r '.[] | "\(.createdAt) \(.databaseId)"' \
            | sort -r \
            | awk "NR>$KEEP_RUNS {print \$2}" \
            | while read -r run_id; do
                gh api -X DELETE "repos/${{ github.repository }}/actions/runs/$run_id"
              done
```

- [ ] **Step 4: Replace the batch workflow with a reusable-workflow matrix caller**

Use this complete structure in `.github/workflows/release_wrt_all.yml`, listing every paired upstream device from `wrt_core/compilecfg` and `wrt_core/deconfig`:

```yaml
name: Release Wrt - All Models

on:
  workflow_dispatch:
    inputs:
      add_fragments:
        description: Add config fragments, comma separated
        required: false
        default: ""
      remove_fragments:
        description: Remove default config fragments, comma separated
        required: false
        default: ""

permissions:
  actions: write
  contents: write

jobs:
  release:
    strategy:
      fail-fast: false
      max-parallel: 2
      matrix:
        model:
          - aliyun_ap8220_immwrt
          - aliyun_ap8220_libwrt
          - cmcc_rax3000m_immwrt
          - gemtek_w1701k_immwrt
          - jdcloud_ax6000_immwrt
          - jdcloud_ipq60xx_immwrt
          - jdcloud_ipq60xx_libwrt
          - link_nn6000v2_immwrt
          - linksys_mx4x00_immwrt
          - n1_immwrt
          - qihoo_360v6_immwrt
          - redmi_ax5_immwrt
          - redmi_ax6_immwrt
          - redmi_ax6_libwrt
          - x64_immwrt
          - zn_m2_immwrt
          - zn_m2_libwrt
    uses: ./.github/workflows/release_wrt.yml
    with:
      model: ${{ matrix.model }}
      add_fragments: ${{ inputs.add_fragments }}
      remove_fragments: ${{ inputs.remove_fragments }}
    secrets: inherit
```

- [ ] **Step 5: Parse workflows and run static invariants**

```powershell
python -c "from pathlib import Path; import yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in Path('.github/workflows').glob('*.yml')]; print('workflow yaml: PASS')"
python tests/verify_upstream_sync.py
```

Expected: both commands print PASS and exit 0.

- [ ] **Step 6: Commit workflow migration**

```powershell
git add .github/workflows tests/verify_upstream_sync.py
git commit -m "ci: preserve downstream release workflows"
```

---

### Task 6: Run full local verification

**Files:**
- Verify: all tracked `*.sh`, workflow YAML, device `.ini`/`.config` pairs, preservation assets.
- Modify only if a test exposes a specific defect.

**Interfaces:**
- Consumes: completed migration commits.
- Produces: evidence that the branch is safe to integrate.

- [ ] **Step 1: Check every tracked shell script with Git Bash**

```powershell
$bash = 'C:\Program Files\Git\bin\bash.exe'
git ls-files '*.sh' | ForEach-Object { & $bash -n $_; if ($LASTEXITCODE -ne 0) { throw "bash syntax failed: $_" } }
```

Expected: no output and exit 0.

- [ ] **Step 2: Run preservation and banner tests**

```powershell
python tests/verify_upstream_sync.py
& 'C:\Program Files\Git\bin\bash.exe' tests/test_banner.sh
```

Expected: both print PASS.

- [ ] **Step 3: Preview every paired device configuration**

```powershell
$bash = 'C:\Program Files\Git\bin\bash.exe'
$devices = Get-ChildItem wrt_core/compilecfg/*.ini | ForEach-Object { $_.BaseName } | Where-Object { Test-Path "wrt_core/deconfig/$_.config" }
foreach ($device in $devices) {
  & $bash ./build.sh $device config_preview
  if ($LASTEXITCODE -ne 0) { throw "config_preview failed: $device" }
}
```

Expected: all 18 paired devices print their effective fragments and exit 0.

- [ ] **Step 4: Verify Git ancestry, remotes, and diff quality**

```powershell
git merge-base --is-ancestor upstream/main HEAD
git remote -v
git diff --check backup/pre-upstream-sync-20260809..HEAD
git status --short --branch
```

Expected: ancestry exits 0; upstream push URL is `DISABLED`; diff check is empty; working tree is clean.

- [ ] **Step 5: Record any verification-only correction**

If the preceding commands required a correction, stage only the named files and commit with:

```powershell
git commit -m "fix: resolve upstream sync verification findings"
```

Skip this commit when no correction was necessary.

---

### Task 7: Integrate into master and push only to origin

**Files:**
- Update ref: `master`
- Push refs: `origin/master`, `origin/backup/pre-upstream-sync-20260809`

**Interfaces:**
- Consumes: verified `sync/upstream-20260809`.
- Produces: updated downstream repository with a recoverable backup ref.

- [ ] **Step 1: Re-run completion verification immediately before integration**

```powershell
python tests/verify_upstream_sync.py
& 'C:\Program Files\Git\bin\bash.exe' tests/test_banner.sh
git status --short --branch
```

Expected: both tests pass and the working tree is clean.

- [ ] **Step 2: Fast-forward local master**

```powershell
git switch master
git merge --ff-only sync/upstream-20260809
```

Expected: master fast-forwards without a merge conflict.

- [ ] **Step 3: Confirm exact push targets**

```powershell
git remote get-url --push origin
git remote get-url --push upstream
```

Expected: origin is `https://github.com/BlackHu-art/openwrt_release.git`; upstream is `DISABLED`.

- [ ] **Step 4: Push the backup and synchronized master to the downstream repository**

```powershell
git push origin backup/pre-upstream-sync-20260809:backup/pre-upstream-sync-20260809
git push origin master:master
```

Expected: both pushes report success; no force option is used.

- [ ] **Step 5: Verify downstream remote state**

```powershell
git ls-remote --heads origin master backup/pre-upstream-sync-20260809
git status --short --branch
```

Expected: remote master matches local master, remote backup matches `06803a6197f98b800a0f7f4a258321caef2edcda`, and local master is clean.
