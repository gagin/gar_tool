COMMIT_MESSAGE ?= "Updated changes to $(shell git describe --tags --always)"

commit:
	git commit -am "$(COMMIT_MESSAGE)"

.PHONY: commit default

default: commit

%:
	@: