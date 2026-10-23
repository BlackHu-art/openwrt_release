# Managed plugin build sources implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Build HomeProxy, the shared Xray/sing-box recipes, OAF, iStoreX components and Argon/Aurora from reviewed sources in this repository; remove QuickFile's obsolete binary installation rewrite.

**Architecture:** Keep exact upstream package blobs in `wrt_core/managed/packages/`, with source revisions, file hashes and original modes in a lock file. A local materializer checks the complete input before copying packages into the existing source-preparation destinations and restores executable files and relative symlinks. Existing compatibility fixes run at their existing stages. Core source archives remain version/hash-pinned recipe downloads.

**Tech Stack:** Bash source preparation, Python standard library, OpenWrt feeds, existing Windows and Linux regression runners.

**Spec:** The user's approved migration request and the preceding inventory; implement in the current project and push after verification.

## Global constraints

- Do not access or operate the router.
- Do not edit device configs, fragments, user backups or existing unrelated work.
- Preserve SSR/OpenClash/ADG/Passwall fixes, HomeProxy patches and shared Xray validation.
- Keep OAF default/startup adjustments, QuickStart controller/dependency fixes, and Argon integrated settings compatibility.
- A missing or altered managed input fails before replacing the destination; do not fall back to rolling external sources.
- Preserve upstream licenses, exact blobs, symlink targets and executable modes; record package/core source boundaries.
- This work does not claim a complete firmware cross-build or installed-router acceptance.

## Review focus

- Later source updater functions must not replace managed sources with network downloads.
- Parent checkout filters, Windows symlink representation and POSIX permissions must not corrupt built packages.
- Argon's compatibility package must have a single owner and preserve configuration ownership.
- Repeated source preparation must retain expected patches without modifying source snapshots or runtime configuration.
- QuickFile must use the target Rust toolchain output on both x86_64 and ARM64, with unknown/old recipes rejected explicitly.

## Tasks

### Task 1: Local managed source contract

- [ ] Capture upstream source trees, licenses, exact revisions and the existing QuickStart controller override.
- [ ] Add failing tests for full input validation, tampered/missing/extra files, safe materialization, executable modes and symlinks.
- [ ] Implement `wrt_core/managed_plugins.py` and the Bash bridge for manifest validation and package staging.
- [ ] Confirm focused tests pass and input snapshots stay unchanged.

### Task 2: Actual build integration and QuickFile

- [ ] Add failing tests exercising the actual source-preparation paths with network boundaries blocked.
- [ ] Remove managed custom-feed packages from remote imports and stage their local sources before feed indexing.
- [ ] Retain HomeProxy compatibility processing; replace theme downloads and the QuickStart gist download with local inputs.
- [ ] Reproduce the old QuickFile recipe mismatch, remove the obsolete rewrite and validate the modern Rust installation contract.
- [ ] Verify fresh and repeated preparation, existing configuration sentinels, package selection and all prior fixes.

### Task 3: Verification, documentation and publication

- [ ] Add the new checks to both test runners and relevant CI path triggers.
- [ ] Document actual build-owned packages, source refresh procedure, core download boundaries and validation limits.
- [ ] Run the complete Windows regression runner and inspect every result.
- [ ] Perform an independent review of the frozen patch, resolve findings and rerun affected checks.
- [ ] Commit only the reviewed task files, push, and check Linux CI on the committed revision.
