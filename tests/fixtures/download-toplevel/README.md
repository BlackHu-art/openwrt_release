# Download failure regression fixture

`3fd1e27a/download.mk` is the unchanged download block (lines 198–205) from
[`include/toplevel.mk`](https://github.com/VIKINGYFY/immortalwrt/blob/3fd1e27a511851b41cf082b067b60099e8e026c4/include/toplevel.mk#L198-L205)
at VIKINGYFY/immortalwrt commit `3fd1e27a511851b41cf082b067b60099e8e026c4`.
The upstream file is SPDX `GPL-2.0-only`, copyright OpenWrt.org, 2007–2020.

The regression runs this block through real GNU make. Only the expensive child
downloads are replaced with deterministic make targets; download ordering,
recursive exit status, flock/zstd prerequisites and the build wrapper remain
executable behavior. No network or firmware compilation is needed.

## Reviewed 24.10 variant

`ec9ef10e/download.mk` is the unchanged download block (lines 198–205) from
[`include/toplevel.mk`](https://github.com/padavanonly/immortalwrt-mt798x-6.6/blob/ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8/include/toplevel.mk#L198-L205)
at padavanonly/immortalwrt-mt798x-6.6 commit
`ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8` (S20M's pinned 24.10 core).
The original SPDX header is GPL-2.0-only, copyright OpenWrt.org, 2007–2020.

This variant requires flock alone. It has the same SDK branches and recursive
command body, and masks earlier failed child downloads in the same way. The
production adapter recognizes this complete original or repaired block exactly;
it does not accept arbitrary prerequisite lists and does not add zstd to 24.10.
The tests execute both source variants through real GNU make and the production
build wrapper, including every failed child stage, SDK package-only behavior,
mirror recovery, ordering, prerequisites, repeated application, unchanged config,
and unknown/duplicate/mixed recipes refused before make or file writes.

The captured S20M file was independently compared byte-for-byte with GitHub's
immutable source. Its Git blob is `092dff786c99226b8a2ef419f6982a1acceaa588`;
whole-file SHA-256 is
`3d2de2ee9b1caf70e312ccd1b0f5340b6855eb027134a71918320ebfdef5795e`,
and excerpt SHA-256 is
`dfee593358463e1183f9e1c9bcb16087d2242fc96c788597c18e9d68ac81bc11`.

[`sources.json`](sources.json) records provenance for all six currently locked
core identities. The other four reviewed current core files (VIKINGYFY f9b0ce76,
LiBwrt 000a4e74, ImmortalWrt 6003f6b8 and ZqinKing 796897b5) contain the exact
existing flock+zstd block, excerpt SHA-256
`c2a0d2c2a061ebb84a5599ce742e7aa86dabe6857af3a84ab83fce84d3644e89`.
No additional download recipe form was found in those fixed source states.

## Early package prepare host unpacker

The same pinned S20M source also provides the unchanged `tools/Makefile`,
`tools/libdeflate/Makefile`, `include/unpack.mk` and `include/prereq-build.mk`
under `ec9ef10e/`. Their Git blobs and SHA-256 values are recorded in
[`host-tools-sources.json`](host-tools-sources.json). Original GPL-2.0 headers
remain intact.

`test_host_unpack_tools.py` loads the real tools dependency assignments and
unpack implementation. A bounded Make dispatcher retains those target edges;
only compiler/install payload and expensive recursive downloads are isolated.
The actual libdeflate producer recipe's `DECOMPRESS_CMD` override is evaluated
when unpacking a gzip source fixture, proving it can bootstrap through the
prereq-provided staged gzip without its own libdeflate-gzip binary or zstd.
A wrapper invoking the actual system gzip stands in for the compiled tool.
The early miniupnpd source fixture is then unpacked by the real `PKG_UNPACK`.

The regression covers cold flock-only downloads, a preinstalled warm unpacker,
nonexecutable cache output, existing zstd-to-libdeflate dependency behavior,
unselected miniupnpd/native-gzip cores, a failed host build, and successful stale
stamps without installed output. It does not claim to compile the real
libdeflate C implementation, cross-compile miniupnpd or complete firmware.
