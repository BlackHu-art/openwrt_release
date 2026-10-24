ifndef SDK
  DOWNLOAD_DIRS = tools/download toolchain/download package/download target/download
else
  DOWNLOAD_DIRS = package/download
endif

download: .config FORCE $(if $(wildcard $(STAGING_DIR_HOST)/bin/flock),,tools/flock/compile) $(if $(wildcard $(STAGING_DIR_HOST)/bin/zstd),,tools/zstd/compile)
	@+$(foreach dir,$(DOWNLOAD_DIRS),$(SUBMAKE) $(dir);)
