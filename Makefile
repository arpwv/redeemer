SHELL := /bin/bash
ROOT_DIR := $(shell pwd)


PROJECT := $(shell basename $(ROOT_DIR))

PIPENV := pipenv
PYTHON := $(PIPENV) run python3


.PHONY: init build run test lint fmt name sql

init:
	pip3 install pipenv
	$(PIPENV) lock
	$(PIPENV) install --three --dev

ipython:
	$(PIPENV) run ipython

notebook:
	$(PIPENV) run jupyter notebook

install-steem-macos:
	brew install openssl
	env LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" $(PIPENV) install steem