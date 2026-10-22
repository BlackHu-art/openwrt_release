# SSR Plus first initialization repair plan

> **For agentic workers:** Use superpowers:subagent-driven-development for implementation and independent review. The user explicitly authorized implementation, validation, commit and push; do not ask for another execution approval.

**Goal:** A clean image initializes a valid SSR configuration and exposes its CBI sections, while existing nonempty configuration is never replaced by factory defaults.

**Architecture:** Keep the reviewed upstream master baseline and all twelve existing patches unchanged. Add a lock-protected `initialize` command in the imported init script, call it from the actual firstboot initializer with checked failure propagation, and append a release-only r6 patch. Guard and verify both the initializer and its immutable default template in source preparation and package/rootfs artifacts.

**Tech stack:** POSIX/BusyBox shell, OpenWrt rc.common/UCI, Python/Bash regressions, native Linux CI.

**Spec:** User request in this task: check upstream; otherwise repair SSR initialization locally, preserve existing configuration, prove build inclusion, test, commit and push. Absolutely no router traffic or device operations.

## Global constraints

- Work in the current project on master; preserve existing untracked user files and the older dirty attached worktree.
- Do not contact the router by SSH, HTTP, browser, ping, or any other method.
- Do not change SSR cores, unrelated plugins, runtime reset semantics, or unrelated rootfs boundaries.
- Existing nonempty configuration skips factory-default installation, even if malformed. Existing upstream migrations remain; preservation means no replacement with defaults.
- First initialization must not stop services, clear rules, restart DNS, discover processes, or run proxy cores.
- Default installation uses checked same-directory staging, mode0644 and atomic rename; every failure returns nonzero without replacing the existing destination.
- Keep the original12 patch bytes and the runtime helper unchanged so complete r4/r5 states remain recognizable. New repair identity:190-r6 / opkg190-6.
- Source table stays three-column; protect11 upstream files, including initializer and default template. Installed manifest targets:11, with template0644 and executable programs0755. Do not hash mutable /etc/config/shadowsocksr.

## Review focus

- No runtime directories or services exist at first initialization.
- Nonempty user configuration exists and the template is absent or invalid.
- Template copy, permission application, validation or publication fails.
- uci-defaults must return failure instead of concealing initialization errors.
- Complete r4/r5 sources/manifests upgrade correctly; missing or drifted initialization assets stop preparation before changes.

## Task 1: Initialization behavior and regressions

Files: new `wrt_core/patches/ssrplus-firstboot.patch`; new `tests/test_ssrplus_firstboot.py`; unchanged upstream initializer/template fixtures; `wrt_core/compat/ssrplus/source-files.tsv`; append functional patch to patches.list.

- [x] Add regressions exercising actual fully patched init and uci-defaults in an isolated filesystem; observe expected RED before adding production code.
- [x] Implement `ssrp_initialize_config()` plus exported `initialize()` under the existing lock; register `initialize` in EXTRA_COMMANDS.
- [x] For absent/empty destination, validate the checked template, stage beside the destination, apply0644 and atomically publish. For nonempty destination, return success without changing it or requiring the template.
- [x] Replace firstboot reset with checked initialize. Preserve upstream migrations and explicit-reset stop failure behavior.
- [x] Verify fresh/missing/empty config, global/CBI sections, repeat/concurrent initialization, malformed existing preservation, I/O failures, error propagation, and explicit-reset protection.

## Task 2: Source and artifact integration

Files: `wrt_core/modules/plugin_compat.sh`; `wrt_core/ssrplus_verify.py`; `tests/test_ssrplus_artifacts.py`; `tests/test_ssrplus_compat.sh`; version expectations in build-gate tests; new release-only patch; test runner and documentation.

- [x] Add failing verifier cases for mixed installed modes, malformed/unknown/duplicate per-file overrides, and stale r5 package identity.
- [x] Add a validated per-file0644 mode override while retaining the existing global mode option; use it for the template in the manifest and source publish paths.
- [x] Append release-r6 after the unchanged twelve patches plus firstboot patch; update generated repair identity to190-r6.
- [x] Verify11 independent source blobs,11 installed targets,14 ordered patches, initializer/template drift rejection, complete r4/r5 upgrades with genuinely old manifests, and repeated application.
- [x] Add firstboot regression to the standard runner and native Linux stage; document the regression and standard build hooks.

## Task 3: Review and publication

- [x] Independently review runtime behavior and combined integration; resolve actionable findings.
- [ ] Run focused affected tests and actual upstream package preparation twice locally; run the complete project regression suite on Linux CI for the exact pushed commit.
- [ ] Commit only task-owned files and push origin/master after local checks pass.
- [ ] Confirm Linux CI for that exact commit, including real nft/dnsmasq and firstboot checks; fix any concrete failures.
- [ ] Confirm local/remote identity and report test limits. Do not compile/deploy firmware or operate the router.
