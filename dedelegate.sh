#!/usr/bin/env bash
# coding=utf-8
set -e

SRC_DIR=/home/ubuntu/redeemer
export PIPENV_VENV_IN_PROJECT=1

cd "${SRC_DIR}"
pipenv run python ./dedelegate.py --no_broadcast=False --wif=/home/ubuntu/steemactivekey.txt


