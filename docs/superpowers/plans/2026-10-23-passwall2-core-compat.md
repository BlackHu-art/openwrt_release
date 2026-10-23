# Passwall2-only and core compatibility implementation plan

**Goal:** Remove Passwall 1 source and build integration, retain Passwall2, and fix the confirmed core/configuration lifecycle gaps without operating the router or overwriting user settings.

**Architecture:** Keep the shared source-preparation pipeline and immutable upstream inputs. Apply guarded compatibility changes to build copies. Upgrade the reviewed Xray recipe and real validation core together with its required Go toolchain; leave sing-box at 1.14.3 with explicit feature limits.

**Spec:** The user requested removing Passwall and its sources, retaining Passwall2, and delegated the other confirmed fixes. Prior reviews are recorded in the ignored core-support and migration-recheck evidence directories. Implementation proceeds in the current project, as previously requested, without another design approval round.

## Global constraints

- Do not access or operate the router, or change runtime/backup configuration.
- Preserve existing explicit settings, SSR node references and subscription parameters.
- Remove Passwall 1 package snapshots, manifest/licenses specific to that snapshot, build imports/selection/patches and test dependence; retain Passwall2 and unrelated upstream theme assets.
- Do not mechanically convert existing h2/QUIC nodes to a different remote protocol.
- Preserve raw managed source bytes and apply runtime changes to guarded build copies.
- Keep real Xray, Ruby 3.4 and Node validation mandatory. Source/host tests do not constitute firmware cross-build acceptance.
- Preserve the three pre-existing unrelated untracked assets.

## Review focus

- A fresh source preparation and all selected targets must work without any Passwall 1 source directory.
- Existing SSR configs and selected node identities survive successful and failed reparses; unsupported protocols fail explicitly without partial core startup.
- Xray recipe, source hash, Go requirement and official Linux/Windows test binary must agree.
- Old Mihomo cores must not be forced into unsupported TUN stacks; explicit supported stack choices remain intact.
- Fresh install, sysupgrade and online package install/upgrade must preserve settings and manual service control.

## Tasks

- [x] Remove Passwall 1 inputs/integration; migrate common test adapters and shared validation to Passwall2-only; add absence/selection regression.
- [x] Upgrade guarded Xray to 26.10.21 and Go >=1.27.3, with verified release provenance and actual MASQUE/ordinary configuration checks.
- [x] Fix SSR mKCP/Gecko fields and explicit unsupported legacy transport handling; add subscription-to-selected-node-to-real-core regression and update release receipts.
- [x] Restore HomeProxy's valid disable_expire mapping and adapt OpenClash TUN defaults/capability checks while preserving existing choices.
- [x] Fix Aurora old-schema preservation and Argon fill-only defaults; test actual initialization on fresh/retained settings.
- [x] Fix OAF online postinst/start ordering without blocking later manual startup; test actual package lifecycle boundaries.
- [x] Refresh stale NSS config intent where the actual core no longer supports that choice; retain per-core supported selection.
- [x] Integrate regression runners/CI paths and documentation; run focused red/green checks and complete shared regression.
- [ ] Freeze the final patch, obtain independent review, resolve findings, then commit/push and check the published Linux CI using the established workflow.

## Ownership and execution

The coordinator owns Passwall removal, shared test adapters, global pipeline registration, documentation and final integration. Independent implementation workers own SSR transport fixes, Xray/toolchain upgrade, and HomeProxy/OpenClash fixes respectively. Later lifecycle work is delegated when a worker slot becomes free. Shared files are edited only by their named owner; workers report required integration changes instead of racing writes.

Each behavior change starts with a regression that demonstrates the existing failure, then the smallest production repair, then focused validation. Existing immutable source fixtures remain unchanged unless a versioned receipt explicitly requires a derived snapshot refresh. The final regression includes the previously fixed SSR initialization, references, DNS, OpenClash download/Ruby/Node and ADG channel paths.
