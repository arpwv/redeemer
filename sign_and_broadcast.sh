#!/usr/bin/env bash
# coding=utf-8

sudo apt-get update
sudo apt-get install python3-pip libssl-dev
pip3 install pipenv
export PIPENV_VENV_IN_PROJECT=1
pipenv install steem
pipenv run





