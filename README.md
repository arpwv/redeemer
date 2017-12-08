# redeemer

This utility reclaims Steem that was delegated in the process of account creation.
We run it automatically.

## Installation and usage

```
$ docker build -t redeemer .
...
$ docker run -it redeemer --help
usage: redeemer [-h] [--delegation_type DELEGATION_TYPE] [--wif WIF]
                [--ops OPS] [--stats] [--no_broadcast]
                [--signing_start_index SIGNING_START_INDEX]
                [--log_level LOG_LEVEL]

optional arguments:
  -h, --help            show this help message and exit
  --delegation_type DELEGATION_TYPE
  --wif WIF             The flag expects a path to a file. The environment
                        variable REDEEMER_WIF will be checked for a literal
                        WIF also.
  --ops OPS
  --stats
  --no_broadcast
  --signing_start_index SIGNING_START_INDEX
  --log_level LOG_LEVEL
```
