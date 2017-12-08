SHELL := /bin/bash
ROOT_DIR := $(shell pwd)


PROJECT_NAME := $(shell basename $(ROOT_DIR))

PIPENV := pipenv
PYTHON := $(PIPENV) run python3

SPAM_REPO = steemit/steempunks
SPAM_REPO_GIT_URL := git@github.com:$(SPAM_REPO).git
LOCAL_SPAM_REPO := /tmp/spam_repo/
SPAM_REPO_LIST_FILES := /hacks/roadscape/badbots/bots-1.lst \
	hacks/roadscape/badbots/bots-2.lst \
	hacks/gandalf/badbots/dart_vesting.lst

LOCAL_SPAM_REPO_FILES := $(addprefix $(LOCAL_SPAM_REPO), $(SPAM_REPO_LIST_FILES))

.PHONY: init
init:
	pip3 install pipenv
	if [[ $(shell uname) == 'Darwin' ]]; then \
		brew install openssl; \
		env LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" $(PIPENV) install --three --dev; \
	else \
		$(PIPENV) install --three --dev; \
	fi


.PHONY: line
lint:
	pipenv pre-commit run pylint --all-files

.PHONY: fmt
fmt:
	pipenv run yapf --in-place --style pep8  *.py
	pipenv run autopep8 --aggressive --in-place  *.py
	pipenv run autoflake --remove-all-unused-imports --in-place *.py

.PHONY: pre-commit
pre-commit:
	pipenv run pre-commit run

.PHONY: pre-commit-all
pre-commit-all:
	pipenv run pre-commit run --all-files

.PHONY: mypy
mypy:
	pipenv run mypy --ignore-missing-imports $(PROJECT_NAME)

.PHONY: ipython
ipython:
	$(PIPENV) run ipython

.PHONY: notebook
notebook:
	$(PIPENV) run jupyter notebook

.PHONY: install-steem-macos
install-steem-macos: pipenv
	if [[ $(shell uname) == 'Darwin' ]]; then \
		brew install openssl; \
		env LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" $(PIPENV) install steem; \
	fi

$(LOCAL_SPAM_REPO):
	git clone $(SPAM_REPO_GIT_URL) $@

spam_accounts.txt: $(LOCAL_SPAM_REPO)
	$(foreach list,$(LOCAL_SPAM_REPO_FILES),$(shell cat $(list) >> /tmp/$@))
	$(shell sort /tmp/$@ > /tmp/$@.sorted)
	$(shell uniq /tmp/$@.sorted > $@)

.PHONY: clean-results
clean-results:
	-rm processed.json
	-rm unprocessed.json
