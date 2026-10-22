# SSR selected node reference preservation implementation plan

> **For agentic workers:** Follow test-driven development and independent review. Steps use checkbox syntax.

**Goal:** Preserve main, UDP, SOCKS5 and Netflix selections when actual subscription reparsing corrects a historical native SS percent-looking password.

**Architecture:** Append ssrplus-node-references.patch after all23published r10 patches, then release-r11. Compute the exact historical native Base64 SS password hash privately, require an unambiguous same-group match with consistent node fields, and update the existing SID in place through the existing transaction journal. Preserve all published patches, runtime, initialization, template, generator and12source guards.

**Tech stack:** Lua5.1, Python unittest/Lupa, actual pinned generator with isolated OS/UCI boundaries, Git Bash local focused checks and Linux CI full project/native checks.

**Spec:** User authorized this node-reference fix, selected-node-to-final-core regressions, fresh/retained review, future-build integration, commit and push. Router operations are forbidden.

## Constraints and review focus

- Work in current master as authorized; preserve original three untracked user paths and unrelated worktrees.
- No router/device/private-backup access, installs or host network/service changes.
- Keep the corrected literal password authoritative; historical decoding is used only for a private compatibility lookup, never final node values or UCI metadata.
- Restrict matching to native Base64 SS, the same subscription group and exact historical hash; verify type, endpoint, port, method, alias and previous password. Do not infer matches from aliases alone or match manual/cross-group nodes.
- Ambiguous matches fail before UCI mutation; old nodes, references and MD5 remain. Historical hash serialization failure must not reject valid new passwords such as literal `%FF`.
- Retaining the SID preserves all four references without rewriting user selections; update nodes and hash before one checked restart, using existing rollback/conflict protection.
- No initialization/config/cache migration. Only actual subscription reparse participates; an unchanged MD5 remains a no-op.
- Identity190-r11/opkg190-11,25patches,12protectedtargets; keep genuine r4..r10 source and original manifest counts.

## Task 1: Actual selected-node regressions and transaction repair

- [ ] Reproduce wrong main selection and dangling UDP/SOCKS/Netflix references on r10 using real Lua subscriber and generator.
- [ ] Add same-node and distinct-node selection cases, actual protocol-role args, cached update, failed commit/restart and ambiguity controls.
- [ ] Append scoped compatibility matching patch and shared test loader; keep all historical source bytes.
- [ ] Run selected-node JSON and subscriber transaction regressions green, including malformed compatibility serialization and no leaked metadata.

## Task 2: Retained configuration and build chain

- [ ] Extend full defaults-hook preservation with all four references and explicit enabled SOCKS/Netflix settings; rerun23firstboot cases.
- [ ] Capture r11 version expectation RED, append release-r11 and update source/package/rootfs identities.
- [ ] Add authentic r10/23patch/12target upgrade coverage; preserve all prior manifests and failure guards.
- [ ] Audit full public source and authentic r10 upgrade for final-byte equality, manifest hashes/modes and idempotence.

## Task 3: Review and publication

- [ ] Freeze inputs, review independently and fix actionable findings with covering tests.
- [ ] Run affected local suites; reserve the complete slow unrelated matrices and native checks for exact-commit Linux CI.
- [ ] Commit task files, push authorized master and verify remote SHA and full CI success.
- [ ] Report preservation behavior and limits: no firmware cross-build, real native core handshake or router acceptance.
