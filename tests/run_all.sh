#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

python tests/verify_upstream_sync.py
python tests/test_plugin_selection.py
bash tests/test_custom_feed_plugins.sh
bash tests/test_plugin_runtime.sh
bash tests/test_banner.sh
bash tests/test_repo_checkout.sh
bash tests/test_homeproxy_compat.sh
bash tests/test_homeproxy_routing.sh
bash tests/test_argon_compat.sh
bash tests/test_miniupnpd_compat.sh
bash tests/test_libffi_compat.sh
bash tests/test_build_steps.sh
bash tests/test_docker_stack_gate.sh
bash tests/test_packit_rootfs.sh
python tests/test_workflow_inputs.py
