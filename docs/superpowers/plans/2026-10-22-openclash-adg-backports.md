# OpenClash and AdGuard Home upstream fixes implementation plan

> **For agentic workers:** Use test-driven implementation and independent review. Steps use checkbox syntax.

**Goal:** Backport currently applicable upstream fixes into the shared source preparation flow while preserving existing user configuration and plugin defaults.

**Architecture:** Retain the reviewed OpenClash 0.48.002 and ZqinKing AdGuard Home baselines. Append OpenClash Ruby AST, dashboard and filename validation patches. Append the AdGuard no-update UPX fix; normalize its dependent patch stack in scratch before any package write, with exact upstream blob guards. Defer the proposed upstream WAN guard after independent review reproduces a custom-WAN regression.

**Tech Stack:** Bash, Python unittest, Node JavaScript VM, Ruby regression tests, fixed public upstream fixtures.

**Spec:** The user requested checking OpenClash/AdGuard upstream fixes and integrating applicable fixes into the current project. Existing no-router boundary remains. Commit/push is not part of this implementation plan.

## Global constraints

- Preserve the three original untracked user paths and all published SSR patches.
- Never connect to the router, inspect private backups, install host dependencies, or change host services/routing.
- Preserve existing OpenClash WAN-subnet/checksum and ADG safety patch bytes; no wholesale dev/UI/core upgrade.
- Keep OpenClash defaults, ADG stable channel, custom links, config/conffiles and actual-download UPX behavior.
- Do not include unrelated shared LuCI upload-limit changes, feature-only ENV expansion or broader UI rewrites.

## Review focus

- WAN exclusion must not reject a single-NIC interface shared with LAN; fw3/fw4 and IPv4/IPv6 paths need checks.
- A no-update ADG check must preserve the installed binary even with UPX configured and failing.
- Reapplying dependent ADG patches must preserve bytes/mtime; partial or unknown source changes must fail before real writes.
- Ruby 3.4 numeric/regex/VCALL AST nodes must work without allowing arbitrary dangerous overwrite calls.
- Dashboard success/error/delete status must update the requested card, independently of the card initialized first.
- Filename validation must agree between Lua/JavaScript and retain Chinese/space names while rejecting paths and shell characters before any write.

## Tasks

- [ ] Record exact primary upstream commits, stable source blobs and compatible backport scope.
- [ ] Reproduce ADG no-update UPX failures, append fix and cover actual upgrade/force controls.
- [ ] Add ADG ordered scratch preparation and four-state/idempotence/source-drift regressions.
- [ ] Reproduce Ruby guard/dashboard failures; append exact small backports and functional tests.
- [x] Audit the upstream WAN guard with command-generation regressions; defer it after reproducing incorrect custom-WAN zone selection and identifying IPv6-only-zone risk.
- [ ] Reproduce unsafe filename/directory handling and backport the shared validator with Lua/JavaScript functional regressions.
- [ ] Update shared build hooks, test entrypoints, Linux validation dependencies and provenance documentation.
- [ ] Run affected tests, full-source apply/repeat audits, review the final immutable diff and report verification limits.
