#!/bin/bash
source /root/.local/share/virtualenvs/app*/bin/activate
pipenv run /usr/src/app/dedelegate.py
