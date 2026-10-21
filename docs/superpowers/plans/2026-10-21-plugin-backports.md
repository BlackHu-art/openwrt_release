# Plugin compatibility follow-up implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement the independent tasks, then review and verify the integrated patch set.

**Goal:** Include the two reviewed SSR fixes, precise OpenClash checksum matching, and consistent AdGuard Home stable-channel downloads in future firmware builds.

**Architecture:** Retain the selected upstream package sources and guarded build hooks. Extend the SSR ordered patch set, replace the older OpenClash checksum backport, and extend the AdGuard Home safety patch. Verify the actual patched sources rather than parallel test implementations.

**Tech Stack:** OpenWrt shell/Lua packaging, Bash and Python regression harnesses, native Linux CI.

**Spec:** User-approved scope in this task: integrate these fixes, verify build inclusion, commit and push after validation; do not operate the router.

## Constraints and decisions

- Keep SSR on the reviewed `fw876/helloworld` master baseline; do not switch to dev or change proxy cores.
- Preserve SSR lifecycle locking, DNS prepare isolation and private nft snapshot ownership.
- Identify the expanded SSR repair as `190-r5` and include every added patch in its generated manifest.
- Keep OpenClash 0.48.002 and its existing WAN-subnet repair. Preserve upstream's warning-and-skip behavior when no valid checksum is available.
- ADG automatic updates target stable releases. Never automatically downgrade an installed newer version; explicit force retains its existing meaning.
- Reject a downloaded core with the wrong or unreadable version before stopping or replacing the installed core. Preserve user-maintained download links while preventing beta/edge fallback in stable updates.
- Preserve untracked user files. Work in the requested current project; do not touch the older, dirty attached worktree.
- Keep the previously reported unrelated rootfs-gate boundary changes outside this patch set.

## Review focus

- DNS preparation must not add live nft elements before rules exist.
- IPv4 resolver addresses must enter the existing SSR-owned set; this master baseline has no IPv6 GFW rules, so IPv6 literals must be skipped without being truncated into IPv4 addresses.
- Checksum filenames with prefixes, paths, special characters and CRLF must match exactly.
- Preserved legacy ADG links must not silently install beta; failed validation must preserve the running core.
- A previously installed prerelease must compare correctly with its matching stable release.

## Task 1: SSR DNS forwarding and custom ports

Files: new SSR follow-up patches; `wrt_core/compat/ssrplus/patches.list`; new focused shell-source regression tests.

- [x] Add failing tests for nft GFW resolver set insertion, prepare-stage isolation, and global custom-port selection.
- [x] Backport the reviewed changes while preserving the existing lifecycle and DNS transaction boundaries.
- [x] Run the focused tests and the existing affected runtime tests.
- [x] Review patch ordering and complete/repeated application against the actual upstream master source.

## Task 2: OpenClash checksum matching

Files: `wrt_core/patches/openclash-checksum-filename.patch`; new focused checksum regression script.

- [x] Demonstrate failures for a prefix-colliding filename and uppercase SHA with path/CRLF formatting.
- [x] Replace the older matching change with the reviewed exact-basename/hash-normalization backport.
- [x] Verify correct hashes, genuine mismatches, literal special characters, malformed entries, and repeated patch application.

## Task 3: ADG download-channel consistency

Files: `wrt_core/patches/adguardhome-update-safety.patch`; focused ADG channel tests and unchanged source fixtures; ADG section of `tests/test_plugin_runtime.sh` if required.

- [x] Add failing tests exercising the production updater with isolated download, binary and service boundaries.
- [x] Use stable-channel defaults and validate stable release metadata and actual candidate versions.
- [x] Continue to a valid stable mirror after a rejected candidate; reject all-invalid downloads without replacing the existing core.
- [x] Preserve automatic no-downgrade behavior and handle matching stable/prerelease ordering.
- [x] Run old update behavior tests, channel tests, patch idempotence, and full-shell syntax checks.

## Task 4: Build integration, review and publication

Files: SSR release/manifest version references, test runner, fixture provenance and compatibility documentation.

- [x] Bump the SSR repair release and update test expectations without weakening source/artifact checks.
- [x] Add all new focused tests to the standard regression runner used by build/release CI.
- [x] Verify current upstream source snapshots accept the complete production patch helpers twice, with unchanged bytes on the second run.
- [x] Review the combined diff and run `bash tests/run_all.sh` with the existing isolated test dependencies.
- [ ] Commit only task-owned source, tests and public documentation; push the current branch.
- [ ] Confirm native Linux CI, including isolated nft/dnsmasq validation, passes; fix any concrete failures and push follow-up commits if needed.
- [ ] Confirm local and remote commits match. Report validation and full-firmware/device limits explicitly.

## Pre-publication validation

- All three runtime changes and the combined integration received independent review with no actionable findings.
- `bash tests/run_all.sh` completed with exit 0 on Windows, including 47 focused SSR/OpenClash/ADG cases. Seven existing host-dependent Python cases were skipped; native Linux CI remains the publication follow-up.
- Complete reviewed upstream source preparation succeeds twice; repeated output bytes are unchanged. SSR original nine patch bytes remain unchanged, with twelve hashes in the `190-r5` manifest.
- No router access, firmware installation or complete firmware cross-compilation was performed.
