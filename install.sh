#!/usr/bin/env bash
# coding=utf-8
set -e

EC2_HOST=$1
SRC_DIR=/home/ubuntu/redeemer

ssh -A ubuntu@${EC2_HOST} << SSHCMD
set -e
sudo apt-get update
sudo apt-get install python3-pip libssl-dev
export PIPENV_VENV_IN_PROJECT=1
sudo pip3 install pipenv

sudo rm -rf ~/redeemer
sudo rm -f /etc/cron.daily/de_delegate_cron.sh
git clone git@github.com:steemit/redeemer.git

cd redeemer
sudo env PIPENV_VENV_IN_PROJECT=1 pipenv install
sudo cp dedelegate.sh /etc/cron.daily
sudo chmod -R 0700  ${SRC_DIR}
echo 'Added this script to /etc/cron.daily'
less /etc/cron.daily/dedelegate.sh
SSHCMD

