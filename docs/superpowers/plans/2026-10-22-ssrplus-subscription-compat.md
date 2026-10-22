# SSR subscription compatibility implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and independently review this plan. Steps use checkbox syntax.

**Goal:** Repair retained automatic SS selection, backport upstream SS credentials parsing, and decode transport parameters once while preserving explicit user settings.

**Architecture:** Append separate migration and parser patches plus a release-r8 patch after all sixteen published r7 patches. Keep the eleven independently checked upstream inputs and runtime helper unchanged. Extend real-hook and actual Lua subscriber regressions, including the real pinned lua-neturl dependency, and retain build/package/rootfs gates.

**Tech stack:** BusyBox-compatible shell, Lua 5.1, Python unittest, Git Bash locally and Linux CI.

**Spec:** The user's 2026-10-22 instruction following the three confirmed review findings in this conversation. Implementation, validation, commit and push are authorized; router access is forbidden.

## Global constraints

- Work in the current project as explicitly requested; preserve all existing untracked user files and other worktrees.
- No router, device, private backup, service, host-network or global configuration operations.
- Preserve existing explicit SS preferences, including empty, auto, Rust, libev, Xray and custom values; do not guess whether an existing Rust value originated from r6.
- Only stop the legacy migration from inserting Rust when the SS preference is absent; leave unrelated migrations intact.
- Backport fw876/helloworld commit 16617bee81157f68965994125b88ee74a822faa5 to the reviewed master baseline, adapting helper dependencies rather than replacing the plugin with dev.
- Existing sixteen patches, runtime and eleven upstream fixture inputs stay byte-identical. New identity is 190-r8 / opkg190-8; old complete r4/r5/r6/r7 states must normalize safely.

## Review focus

- Fresh missing and empty configs still initialize; retained absent preferences stay automatic after repeated hooks.
- Explicit preferences, selected nodes, subscription settings and domain/IP rules survive retained upgrades.
- SIP002, whole-link Base64, plain and percent-encoded credentials preserve literal plus signs and reserved characters; malformed links never publish invalid nodes.
- WS, HTTPUpgrade, XHTTP and other affected transports decode query values exactly once, including percent, plus, slash, TLS and extra JSON values.
- The real pinned lua-neturl parser, partial subscription failures and compiled package/rootfs identity remain covered.

### Task 1: Runtime fixes and regression tests

- [ ] Extend firstboot and subscription tests, using checked public URL-module fixtures where needed; run them against r7 and record expected failures.
- [ ] Append ssrplus-subscription-auto.patch and ssrplus-ss-parser.patch with the three scoped fixes; run the affected suites green.
- [ ] Independently review upstream adaptation, explicit-setting preservation and transport encoding semantics.

### Task 2: Build integration and provenance

- [ ] Append ssrplus-release-r8.patch; update helper identity and artifact/build gates to 190-r8.
- [ ] Extend compatibility tests with genuine complete r7 sources/manifests, retaining historic patch counts and prior upgrade cases.
- [ ] Update compatibility documentation, provenance and regression instructions without modifying immutable upstream fixtures.
- [ ] Run focused gates and one complete project suite; verify a full pinned upstream package, idempotence and all installed targets.

### Task 3: Final review and publication

- [ ] Review the final diff independently; resolve actionable findings and rerun affected checks.
- [ ] Verify preserved inputs, whitespace, package identity and build-entry propagation.
- [ ] Commit only this task's files, push the authorized branch and inspect exact-commit Linux CI, including isolated native DNS/nft checks.
- [ ] Report changes, tests, commit/push status and firmware/device acceptance limits accurately.
