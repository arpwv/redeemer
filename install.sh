#!/usr/bin/env bash
# coding=utf-8
set -e

EC2_HOST=$1
SRC_DIR=/home/ubuntu/redeemer

ssh -A ubuntu@${EC2_HOST} << SSHCMD
set -e
sudo apt-get update
sudo apt-get install python3-pip libssl-dev
rm -rf ~/redeemer
rm -f /etc/cron.daily/de_delegate_cron.sh
git clone git@github.com:steemit/redeemer.git
cd redeemer
pip3 install pipenv
export PIPENV_VENV_IN_PROJECT=1
pipenv install --three
sudo chown -R root ${SRC_DIR}
sudo chmod -R 0755  ${SRC_DIR}
sudo echo "cd ${SRC_DIR} && pipenv run python ./dedelegate.py --no_broadcast=True"  > /etc/cron.daily/dedelegate.sh
SSHCMD

