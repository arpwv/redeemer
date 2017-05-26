# redeemer

## spec

### functions
1. list all accounts with delegated steem power
2. review activity of those accounts
3. revoke or extend delegated steem power based on account activity rules
  -  posts
  - comments
  - votes
  - follows


### deployment
1. executed at configurable interval
2. packaged as docker container
3. decide whether to use long-running container with internal cron execution or external cron/trigger of execute on startup container
4. reusable design for future tasks
