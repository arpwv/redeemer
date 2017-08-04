#!/usr/bin/env bash
# coding=utf-8
set -e

EC2_HOST=$1
SRC_DIR=/home/ubuntu/redeemer

ssh -A ubuntu@${EC2_HOST} << SSHCMD
set -e
sudo apt-get update
sudo apt-get install python3-pip libssl-dev
sudo rm -rf /home/ubuntu/redeemer
sudo rm -f /etc/cron.daily/dedelegate.sh
git clone git@github.com:steemit/redeemer.git
cd redeemer
sudo su root
pip3 install pipenv
env PIPENV_VENV_IN_PROJECT=1 pipenv install
cp dedelegate.sh /etc/cron.daily
chmod -R 0700  ${SRC_DIR}
echo 'Added this script to /etc/cron.daily'
less /etc/cron.daily/dedelegate.sh
SSHCMD