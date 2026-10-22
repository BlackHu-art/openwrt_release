# SSR initialization order repair plan

> **For agentic workers:** Use test-driven implementation and independent review. The user explicitly authorized the local repair, verification, commit and push; no additional execution approval is needed.

**Goal:** Fresh SSR defaults retain automatic subscription core selection and transport parameters; retained configuration follows its existing migrations without factory replacement.

**Architecture:** Keep the published fourteen r6 patches unchanged. Append an order-only patch placing checked `initialize` at the former reset position, after the existing-config migration branch and before sed conversions. Append release-r7 and carry the identity through source/artifact gates. Exercise actual hook results and the patched Lua subscriber together.

**Tech stack:** POSIX shell, Python unittest, UCI OS boundary, Lua 5.1/Lupa, Bash compatibility checks, native Linux CI.

**Spec:** Current user request and the confirmed P2 review in `.superpowers/sdd/2026-10-22-ssrplus-firstboot/recheck-upgrade.md`.

## Global constraints

- Absolutely no router/device traffic or operations, including read-only SSH, HTTP, browser or ping.
- Baseline is master `2f3ac2eecda769ae9a7193808e0eeec914055426`; preserve user untracked assets and the older dirty worktree.
- Preserve all fourteen published patches, runtime helper, source table and immutable fixtures byte for byte; append two patches for sixteen total.
- Retain the eleven-source/eleven-installed-file manifest and template0644/program0755 policy; active user configuration is not an artifact hash target.
- New identity is190-r7/opkg190-7. Support genuine r4/r5/r6 source/manifests and repeated preparation.
- Existing nonempty configuration is never replaced with defaults; its original migrations and sed conversions remain. Explicit user core preferences, nodes and domain/IP rules survive.
- First initialization keeps its lock, same-filesystem atomic publication, absolute UCI validation and checked failure/retry behavior. No new service, network or reset operation.
- No dependency installation or full firmware build; focused local checks then exact pushed-commit full Linux runner and native DNS/nft checks.

## Review focus

- Missing/zero configurations skip legacy migrations and keep ss_type/xray_hy2_type unset as in the original template.
- Actual output from the full hook feeds actual Lua node construction: ordinary SS uses available libev, SS WebSocket uses Xray with host/path/transport intact.
- Retained current and legacy configurations preserve user values while receiving only the existing migrations, including type conversions.
- Initialization failure leaves the hook available for retry and does not publish partial defaults; retry succeeds.
- Published r6 manifests retain their original14patches/11targets when testing upgrades; r4/r5 retain9targets and9/12patches.

## Task 1: Repair, semantic regressions and build integration

- [ ] Write focused regressions using a stateful UCI boundary for the commands the real defaults hook uses. Assert resulting values, not only recorded calls. Do not implement an unrelated general UCI emulator.
- [ ] Run the new fresh-default/core/transport cases against r6 and observe assertion failures before production edits.
- [ ] Append `ssrplus-initialization-order.patch` then `ssrplus-release-r7.patch`; keep the real init implementation and subscriber unchanged.
- [ ] Test missing/empty configs, available libev, Rust+Xray WebSocket SS, explicit existing preferences, nodes/domain/IP rules and legacy migrations. Tie node assertions to the values emitted by the full hook.
- [ ] Update version expectations and source preparation identity; extend compatibility tests to genuine r6 upgrades and r6 package rejection.
- [ ] Update existing compatibility docs and standard runner only as needed; describe OS-boundary and real-device validation limits accurately.
- [ ] Run affected firstboot/subscription, artifact/build-gate and focused compatibility checks. Report exact RED/GREEN evidence and freeze the files for review.

## Task 2: Independent review and publication

- [ ] Independently review the immutable diff for fresh-flash and retained-config behavior, test fidelity, release/artifact integration and scope.
- [ ] Verify the full pinned upstream package prepares twice without drift; confirm old14/runtime/source/fixture bytes are unchanged.
- [ ] Run focused local checks, commit only task-owned files, and push master.
- [ ] Verify complete project regression plus native DNS/nft checks on the exact pushed commit, resolve failures, then confirm remote identity and tracked cleanliness.
- [ ] Report changes, evidence and limits; no router operations or firmware deployment.
