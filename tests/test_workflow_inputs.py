#!/usr/bin/env python3
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [
    ROOT / ".github/workflows/release_wrt.yml",
    ROOT / ".github/workflows/build_wrt.yml",
]


def workflow_steps(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["build"]["steps"]


def step_named(steps, name):
    return next(step for step in steps if step.get("name") == name)


for workflow in WORKFLOWS:
    text = workflow.read_text(encoding="utf-8")
    assert "hashFiles(" not in text, f"legacy repo_flag scan remains in {workflow.name}"
    steps = workflow_steps(workflow)
    cache = step_named(steps, "Cache Dependencies")
    key = cache["with"]["key"]
    restores = cache["with"]["restore-keys"].splitlines()
    deletion = step_named(steps, "Delete Old Cache")["run"]
    assert "${{ env.REPO_HASH }}" in key
    assert all("${{ env.REPO_HASH }}" in item for item in restores)
    assert "${{ env.REPO_HASH }}" in deletion
    logs = step_named(steps, "Upload Build Logs")
    assert logs["if"] == "${{ !cancelled() }}"
    assert logs["with"]["path"] == "./action_build/logs/"
    assert "${{ inputs.model }}" in logs["with"]["name"]
    assert steps.index(logs) > steps.index(step_named(steps, "Build Firmware"))
    assert step_named(steps, "Machine Information (Post-build)")["if"] == "${{ !cancelled() }}"
    for dimension in [
        "${{ matrix.os }}",
        "${{ inputs.model }}",
        "${{ env.ADD_CONFIG_FRAGMENTS_KEY }}",
        "${{ env.REMOVE_CONFIG_FRAGMENTS_KEY }}",
        "${{ env.BUILD_DATE }}",
    ]:
        assert dimension in key, f"{workflow.name} cache key lost {dimension}"

release_steps = workflow_steps(WORKFLOWS[0])
select_index = next(
    index for index, step in enumerate(release_steps) if step.get("name") == "Select Packit Rootfs"
)
packit_index = next(
    index
    for index, step in enumerate(release_steps)
    if step.get("uses") == "unifreq/openwrt_packit@8007d3efd49bb42aa20c5755a50af21dc7a438e1"
)
select_step = release_steps[select_index]
packit_step = release_steps[packit_index]
assert select_index < packit_index
assert select_step["if"] == packit_step["if"]
assert select_step["run"] == "bash ./wrt_core/ci/select_packit_rootfs.sh"
assert packit_step["env"]["OPENWRT_ARMVIRT"] == "${{ env.OPENWRT_ARMVIRT }}"
assert packit_step["env"]["PACKAGE_SOC"] == "s905d"
assert packit_step["env"]["KERNEL_VERSION_NAME"] == "6.6.y"

print("workflow cache and Packit inputs: PASS")
