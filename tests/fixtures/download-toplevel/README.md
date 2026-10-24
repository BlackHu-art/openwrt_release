# Download failure regression fixture

`3fd1e27a/download.mk` is the unchanged download block (lines 198–205) from
[`include/toplevel.mk`](https://github.com/VIKINGYFY/immortalwrt/blob/3fd1e27a511851b41cf082b067b60099e8e026c4/include/toplevel.mk#L198-L205)
at VIKINGYFY/immortalwrt commit `3fd1e27a511851b41cf082b067b60099e8e026c4`.
The upstream file is SPDX `GPL-2.0-only`, copyright OpenWrt.org, 2007–2020.

The regression runs this block through real GNU make. Only the expensive child
downloads are replaced with deterministic make targets; download ordering,
recursive exit status, flock/zstd prerequisites and the build wrapper remain
executable behavior. No network or firmware compilation is needed.
