COMMIT_MESSAGE ?= $(strip Updated changes to $(shell git describe --tags --always))

commit:
	git add --update
	git commit -m "$(COMMIT_MESSAGE)"

.PHONY: commit default

default: commit

%:
	@: