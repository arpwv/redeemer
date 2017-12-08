FROM python:3.6

RUN pip install pipenv

WORKDIR /usr/src/app
ADD Pipfile Pipfile.lock ./
RUN pipenv install
ADD . .

ENTRYPOINT [ "pipenv", "run", "./dedelegate.py" ]
