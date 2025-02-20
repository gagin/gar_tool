COMMIT_MESSAGE ?= "Updated changes to $(shell git describe --tags --always)"

commit:
	git add .
	git commit -m "$(strip $(COMMIT_MESSAGE))"

.PHONY: commit default

default: commit

%:
	@:
