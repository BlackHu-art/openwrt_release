# Shared proxy core fixture

`small-package-3d560925/xray-core/Makefile` is the exact Git blob
`481e0342987bde364588e00ec716c1f23a250512` from
`kenzok8/small-package` commit
`3d5609257639ed76aaacdeffe242343d51265fea`, path `xray-core/Makefile`.
It retains the original MPL-2.0 package license declaration. No Xray source or
binary is vendored here.

The Python tests create two minimal generator declarations and a Go recipe in a
temporary directory. They exercise the actual build helper without fetching or
executing an upstream package. The generator declarations reflect
`local xray_min_version = "26.7.11"` in both currently reviewed Passwall
generators; their complete provenance is recorded in
`wrt_core/compat/proxy-cores/xray-26.7.11.json`.

Version 26.7.11 is the minimum required by those generators. Its official GitHub
release is marked **prerelease**, not stable. The target source archive, tag
commit, Go requirement, and reviewed recipe hashes are recorded in that receipt.
