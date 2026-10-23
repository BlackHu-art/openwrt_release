#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

python tests/verify_upstream_sync.py
python tests/test_windows_test_env.py
python tests/test_validation_gates.py
python tests/test_plugin_selection.py
python tests/test_xray_core_compat.py
python tests/test_passwall_tls.py
python tests/test_passwall_launch.py
python tests/test_proxy_compat_pipeline.py
python tests/test_shared_xray_compat.py
bash tests/test_custom_feed_plugins.sh
bash tests/test_plugin_runtime.sh
bash tests/test_openclash_checksum.sh
bash tests/test_adguard_channel.sh
python tests/test_adguard_compat.py
python tests/test_openclash_backports.py
python tests/test_openclash_filename.py
bash tests/test_banner.sh
bash tests/test_repo_checkout.sh
bash tests/test_homeproxy_compat.sh
bash tests/test_homeproxy_routing.sh
bash tests/test_ssrplus_compat.sh
python tests/test_ssrplus_runtime_regressions.py
python tests/test_ssrplus_updater_regressions.py
python tests/test_ssrplus_runtime.py
python tests/test_ssrplus_followup_fixes.py
python tests/test_ssrplus_firstboot.py
python tests/test_ssrplus_persistence.py
python tests/test_ssrplus_persistence_lifecycle.py
python tests/test_ssrplus_subscription.py
python tests/test_ssrplus_core_config.py
python tests/test_ssrplus_monitor_scheduler.py
python tests/test_ssrplus_availability.py
python tests/test_ssrplus_artifacts.py
python tests/test_ssrplus_build_gate.py
bash tests/test_argon_compat.sh
bash tests/test_miniupnpd_compat.sh
bash tests/test_libffi_compat.sh
bash tests/test_build_steps.sh
bash tests/test_docker_stack_gate.sh
bash tests/test_packit_rootfs.sh
python tests/test_workflow_inputs.py
