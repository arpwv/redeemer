# redeemer

This utility reclaims Steem that was delegated in the process of account creation.
We run it automatically.

## Installation and usage

```
$ docker build -t redeemer .
...
$ docker run -it redeemer --help

usage: redeemer [-h] [--sendgrid_api_key SENDGRID_API_KEY]
                [--send_messages_to SEND_MESSAGES_TO]
                [--notification_interval NOTIFICATION_INTERVAL]
                [--account ACCOUNT] [--wif WIF] [--log_level LOG_LEVEL]
                [--dry_run DRY_RUN] [--interval INTERVAL]

optional arguments:
  -h, --help            show this help message and exit
  --sendgrid_api_key SENDGRID_API_KEY
                        api key to use Sendgrid to send notification messages (default: None)
  --send_messages_to SEND_MESSAGES_TO
                        email address to send messages to (default: None)
  --notification_interval NOTIFICATION_INTERVAL
                        time in seconds between status emails (default: 86400)
  --account ACCOUNT     Account to perform delegations for (default: None)
  --wif WIF             An active WIF for account. The flag expects a path to a file. The environment variable REDEEMER_WIF will be checked for a literal WIF also. (default: None)
  --log_level LOG_LEVEL
  --dry_run DRY_RUN     Set this to false to actually broadcast transactions (default: True)
  --interval INTERVAL   Time in seconds to wait between polling for new delegations (default: 7200)
```
