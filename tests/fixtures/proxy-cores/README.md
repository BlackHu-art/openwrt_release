# Shared proxy core fixture

`small-package-3d560925/xray-core/Makefile` is the exact Git blob
`481e0342987bde364588e00ec716c1f23a250512` from
`kenzok8/small-package` commit
`3d5609257639ed76aaacdeffe242343d51265fea`, path `xray-core/Makefile`.
It retains the original MPL-2.0 package license declaration. No Xray source or
binary is vendored here.

The Python tests create a minimal Passwall2 generator declaration and a Go recipe
in a temporary directory. They exercise the actual build helper without fetching
or executing an upstream package. Passwall2 still declares 26.7.11 as its minimum,
but MASQUE configurations require the reviewed target 26.10.21. Complete source,
release and official validation-core provenance is recorded in
`wrt_core/compat/proxy-cores/xray-26.10.21.json`.

The actual build gate also requires Go >=1.27.3. The official release API marks
26.10.21 non-prerelease, while its emergency release notes defer a stable release
to month end. The API flag does not establish broader runtime stability.
