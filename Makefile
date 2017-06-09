SHELL := /bin/bash
ROOT_DIR := $(shell pwd)
DOCS_DIR := $(ROOT_DIR)/docs
DOCS_BUILD_DIR := $(DOCS_DIR)/_build

PROJECT := $(shell basename $(ROOT_DIR))
ENV_DIR := $(ROOT_DIR)/envd

ENVDIR := envdir $(ENV_DIR)
PIPENV := $(ENVDIR) pipenv
PYTHON := $(PIPENV) run python3

WIF_FILE := steem-active.txt

default: build

.PHONY: init build run test lint fmt name sql

init:
	pip3 install pipenv
	$(PIPENV) lock
	$(PIPENV) install --three --dev

build:
	docker build -t steemit/$(PROJECT) .

run:
	docker run steemit/$(PROJECT)

test:
	$(PYTHON) py.test tests

lint:
	 $(PYTHON) py.test --pylint -m pylint $(PROJECT)

fmt:
	$(PYTHON) yapf --recursive --in-place --style pep8 $(PROJECT)
	$(PYTHON) autopep8 --recursive --in-place $(PROJECT)

sql:
	MYSQL_HOME=$(ROOT_DIR) mysql

ipython:
	$(PIPENV) run ipython -i redeem.py

notebook:
	$(PIPENV) run jupyter notebook

install-steem-macos:
	brew install openssl
	env LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" $(PIPENV) install steem

undelegation_ops.json: clean-data
	$(PYTHON) $(ROOT_DIR)/step1__get_undelegation_ops.py

broadcasted_undelegations.json: undelegation_ops.json
	$(PYTHON) step2_sign_with_wif.py $< $(WIF_FILE)

clean-data:
	-rm ./*.json
