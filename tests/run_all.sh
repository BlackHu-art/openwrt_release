#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

python tests/verify_upstream_sync.py
bash tests/test_banner.sh
bash tests/test_repo_checkout.sh
bash tests/test_homeproxy_compat.sh
bash tests/test_miniupnpd_compat.sh
bash tests/test_build_steps.sh
bash tests/test_docker_stack_gate.sh
bash tests/test_packit_rootfs.sh
python tests/test_workflow_inputs.py
