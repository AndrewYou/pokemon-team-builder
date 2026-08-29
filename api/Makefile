# The real Makefile lives at the repository root. This forwards every target so
# that `make seed` works from inside api/ too, which is where people naturally
# try it first.
.DEFAULT_GOAL := help

%:
	@$(MAKE) -C .. $@
