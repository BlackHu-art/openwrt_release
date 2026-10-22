# SSR literal native SS password implementation plan

> **For agentic workers:** Use test-driven development and independent review. Steps use checkbox syntax.

**Goal:** Preserve literal percent sequences in Base64-decoded native SS passwords through final core JSON, without rewriting existing configurations.

**Architecture:** Append a native SS password patch after all twenty-one published r9 patches, followed by a release-r10 patch. Remove only the inner-password URL-decoding heuristic: URI escapes around Base64 still decode at their existing boundary. Keep the generator, twelve source guards, initialization, templates, runtime and historical patches unchanged.

**Tech stack:** Lua 5.1, Python unittest/Lupa, Git Bash for local focused checks and Linux CI for the complete project suite.

**Spec:** User instruction in this conversation authorizes this password fix, configuration preservation, subscription-to-core regression, validation, commit and push; router operations are forbidden.

## Constraints and review focus

- Preserve original untracked user files and unrelated worktrees; work in the current project.
- Never access router/device/private-backup data or alter host services/network settings.
- Preserve all published r9 patches and twelve original protected source rows/fixtures.
- Base64 payload credentials are literal; `%2F`, `%252F`, percent-like invalid escapes, plus and colon must reach native Rust/libev unchanged.
- Retain ordinary slash passwords, outer URI percent decoding, Base64URL and whole-link Base64 behavior.
- No config migration or replacement of retained nodes; a subscription refresh applies the corrected parser.
- New identity190-r10/opkg190-10;23patches;12installedtargets; genuine historicr4..r9 source states remain covered.

## Task 1: Reproduce and fix the password boundary

- [ ] Add regression cases exercising actual subscriber, committed node and actual final core generator; observe r9 failure.
- [ ] Append ssrplus-ss-password.patch removing the native inner URL-decoding heuristic; load it in the shared test helper.
- [ ] Run actual subscriber/core regressions green and preserve existing explicit core preferences and manual node values.

## Task 2: Compile integration and preservation

- [ ] Extend r10 identity gates RED before metadata changes; append release-r10 and update build/package/rootfs checks.
- [ ] Add authentic r9/21patch/12target upgrade coverage while preserving older manifests and checks.
- [ ] Recheck fresh and retained initialization; retained percent-looking passwords and rule files remain unchanged.
- [ ] Verify a complete pinned upstream package, all23patches/12targets, historical-source upgrades and byte idempotence.

## Task 3: Review and publish

- [ ] Freeze final inputs, obtain independent review and resolve actionable findings.
- [ ] Run affected local suites; avoid repeating slow unchanged Windows plugin matrices. Run the complete project suite and native checks on exact-commit Linux CI after the authorized push.
- [ ] Commit only task files and push current master; verify remote commit and CI success.
- [ ] Report the corrected boundary, retained-config behavior and firmware/device validation limits.
