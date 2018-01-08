# redeemer

This utility reclaims Steem that was delegated in the process of account creation.
We run it automatically.

## Installation and usage

```
$ docker build -t redeemer .
...
$ docker run -it redeemer --help

usage: redeemer [-h] [--account ACCOUNT] [--wif WIF] [--log_level LOG_LEVEL]
                [--dry_run DRY_RUN] [--interval INTERVAL]

optional arguments:
  -h, --help            show this help message and exit
  --account ACCOUNT     Account to perform dedelegations for (default: None)
  --wif WIF             An active WIF for account. The flag expects a path to a file. The environment variable REDEEMER_WIF will be checked for a literal WIF also. (default: None)
  --log_level LOG_LEVEL
  --dry_run DRY_RUN     Set this to false to actually broadcast transactions (default: True)
  --interval INTERVAL   Time in seconds to wait between polling for new delegations (default: 60)
```
