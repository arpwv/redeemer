SHELL := /bin/bash
ROOT_DIR := $(shell pwd)
DOCS_DIR := $(ROOT_DIR)/docs
DOCS_BUILD_DIR := $(DOCS_DIR)/_build

PROJECT := $(shell basename $(ROOT_DIR))
ENV_DIR := $(ROOT_DIR)/envd

ENVDIR := envdir $(ENV_DIR)

PYTHON := pipenv run python3

default: build

.PHONY: init build run test lint fmt name sql

init:
	pip3 install pipenv
	pipenv lock
	pipenv install --three --dev

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
