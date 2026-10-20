# libffi feed-to-core migration fallback

`Makefile` is the unchanged `libs/libffi/Makefile` from
[ImmortalWrt packages 3b7cdf03a6f22e91ae485e1ffdda1062da7a3431](https://github.com/immortalwrt/packages/blob/3b7cdf03a6f22e91ae485e1ffdda1062da7a3431/libs/libffi/Makefile),
Git blob `3a13f71c028bb4bdeff52b10c8a8b5f25aec85e6`. It builds libffi 3.4.7
using the upstream source archive hash.

[70ac3a8440](https://github.com/immortalwrt/packages/commit/70ac3a8440)
removed the recipe when moving libffi into core. The pinned
VIKINGYFY/immortalwrt `3fd1e27a511851b41cf082b067b60099e8e026c4` does not
contain it. Samba4 still requires `python3/host`, which requires `libffi/host`.

`ensure_libffi_source` installs this fallback before feeds installation only
when no `libffi/Makefile` exists under the source tree's package or feeds
directories. Existing upstream recipes take precedence. This does not change
the kernel, NSS sources, package selection, or an already available libffi.

The recipe retains the OpenWrt copyright and GPL-2.0 notice; `COPYING` contains
that license. The library itself uses the MIT license, as recorded in the recipe.
