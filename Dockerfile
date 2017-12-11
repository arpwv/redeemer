FROM python:3.6

RUN apt-get update && \
    apt-get install -y cron && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ADD daily-redeem-delegations.cron /etc/cron.d/daily-redeem-delegations
RUN chmod 0644 /etc/cron.d/daily-redeem-delegations

ADD run-redeemer-from-cron.sh /usr/local/bin/run-redeemer-from-cron.sh
RUN chmod +x /usr/local/bin/run-redeemer-from-cron.sh

RUN touch /var/log/messages

RUN pip install pipenv

WORKDIR /usr/src/app
ADD Pipfile Pipfile.lock ./
RUN pipenv install
ADD . .

ENTRYPOINT [ "pipenv", "run", "./dedelegate.py" ]
