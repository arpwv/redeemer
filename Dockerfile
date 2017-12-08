FROM python:3.6

RUN apt-get update && \
    apt-get install -y cron && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ADD cronjob /etc/cron.d/redeemer-cron
RUN chmod 0644 /etc/cron.d/redeemer-cron

RUN pip install pipenv

WORKDIR /usr/src/app
ADD Pipfile Pipfile.lock ./
RUN pipenv install
ADD . .

ENTRYPOINT [ "pipenv", "run", "/usr/src/app/dedelegate.py" ]
