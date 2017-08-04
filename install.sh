#!/usr/bin/env bash
# coding=utf-8
set -e

EC2_HOST=$1
SRC_DIR=/home/ubuntu/redeemer

ssh -A ubuntu@${EC2_HOST} << SSHCMD
set -e
sudo apt-get update
sudo apt-get install python3-pip libssl-dev
sudo rm -rf ~/redeemer
sudo rm -f /etc/cron.daily/de_delegate_cron.sh
git clone git@github.com:steemit/redeemer.git
cd redeemer
pip3 install pipenv
export PIPENV_VENV_IN_PROJECT=1
pipenv install
echo 'cd /home/ubuntu/redeemer && pipenv run python ./dedelegate.py --no_broadcast=True'  > dedelegate.sh
sudo cp dedelegate.sh /etc/cron.daily
sudo chmod -R 0700  ${SRC_DIR}
SSHCMD

