# Plugin validation integration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore mandatory real Xray, Ruby 3.4 and Node validation, include the existing OpenClash/ADG backports in subsequent builds, and commit/push the verified integration.

**Architecture:** Keep source repair in the existing central preparation pipeline. CI and the Windows private dependency manager supply validated test runtimes and explicitly require them; optional ad-hoc test invocations retain their existing behavior.

**Tech Stack:** GitHub Actions, Bash, Python unittest/PyYAML/Lupa, Xray 26.7.11, Ruby 3.4, Node.

**Spec:** The user's 2026-10-23 instruction in this conversation: repair integration omissions, restore real core validation, complete Windows dependencies, synchronize documentation, validate, commit and push, without router access.

## Global constraints

- Preserve existing SSR 190-r11, Passwall/shared-Xray and OpenClash/ADG fixes; no SSR v198.2 source switch.
- No router, private backup, global PATH or system service changes.
- Install test tools only in a private directory outside the repository; check/run never download missing tools.
- Preserve unrelated .idea, old untracked SSR plan and bytecode assets; explicitly stage task files only.

## Review focus

- Missing required tools fail rather than skip; Ruby below 3.4 fails the guard.
- Malformed/corrupt dependency archives cannot replace working installations.
- CI triggers include all relevant repair inputs and supplied core/runtime variables reach tests.
- Actual source preparation applies previous repairs and rejects unknown drift without rewriting user configuration.
- Documentation distinguishes local regression, Linux CI, firmware cross-build and router acceptance.

## Task 1: CI and mandatory test gates

Files: `.github/workflows/test_ssrplus.yml`, `tests/test_validation_gates.py`, `tests/test_shared_xray_compat.py`, OpenClash test entry points, `tests/run_all.sh`.

- [x] Add regressions for lost core/runtime provisioning, trigger coverage and missing required dependencies; observe failures.
- [x] Restore pinned Xray provisioning, provision Ruby 3.4 and Node, and propagate strict requirements to regression tests.
- [x] Run affected workflow/dependency and plugin tests.

## Task 2: Windows dependency ownership

Files: `tests/windows_test_env.py`, `tests/test_windows_test_env.py`.

- [x] Add failing dependency/environment/archive regressions.
- [x] Manage fixed official Ruby/Node portable archives with hash verification, private installation and required environment checks.
- [x] Run installer contracts, actual private install/check and full Windows regression.

## Task 3: Documentation and build inclusion

Files: plugin compatibility, maintenance and Windows testing documentation; existing four backports, fixtures and source baselines.

- [x] Restore shared-Xray/Passwall documentation and document the OC/ADG patch sets and runtime ownership.
- [x] Verify source preparation entry points, patch inventories, repeatability and original inputs.
- [x] Independently review final changes and run full regressions.
- [ ] Explicitly stage authorized files, commit, push, and inspect the resulting remote CI without claiming firmware/device acceptance.

## Evidence-driven adjustments

- Windows ADG output reproduced a CP936 decoding failure. Explicit UTF-8 subprocess decoding and a required UTF-8 child environment correct it.
- Actual installation reproduced an MSYS fork failure after publishing an executable through an extensionless temporary file. A native regression went from exit 71 to 0 after preserving `.exe` on same-directory atomic staging; installation repairs matching old flock bytes without changing global Git or its DLLs.
- The first full run exercised all 53 real-core inputs and failed at the Windows temporary-file read boundary. Windows now passes the complete generated JSON to Xray's official `stdin:` loader; Linux retains file loading. Real-core positive cases and an invalid-protocol rejection control passed before the complete rerun.
