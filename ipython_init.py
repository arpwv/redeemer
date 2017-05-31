# coding=utf-8
import os
import json
from collections import Counter
from datetime import datetime
from datetime import timedelta
import itertools as it

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy import select, and_, text, union_all, alias

from http_client import SimpleSteemAPIClient


# sbds sql config
ACCOUNTS_TABLE = 'sbds_tx_account_create_with_delegations'
VOTES_TABLE = 'sbds_tx_votes'
COMMENTS_TABLE = 'sbds_tx_comments'
FOLLOWS_TABLE = 'sbds_tx_custom_jsons'

# de-delegation config
DELEGATION_ACCOUNT_CREATOR = 'steem'
MIN_ACCOUNT_AGE_DAYS = 30
EXCLUSIVE_VOTES_THRESHOLD = 2
EXCLUSIVE_COMMENTS_THRESHOLD = 2
EXCLUSIVE_FOLLOWS_THRESHOLD = 0


# db config
db_url = os.environ['DATABASE_URL']
engine = sa.create_engine(db_url, server_side_cursors=True, encoding='utf8', echo=True, execution_options=dict(stream_results=True))
meta = sa.MetaData()
meta.reflect(bind=engine)

accounts_tbl = meta.tables[ACCOUNTS_TABLE]
votes_tbl = meta.tables[VOTES_TABLE]
comments_tbl = meta.tables[COMMENTS_TABLE]
follows_tbl = meta.tables[FOLLOWS_TABLE]


def run_query(engine, query):
    with engine.connect() as conn:
        results = conn.execute(query).fetchall()
    return results


def get_followers(engine, query):
    results = run_query(engine, query)
    follower_count = Counter(f[0] for f in results)
    follower_list = [k for k,v in follower_count.items() if v >= EXCLUSIVE_FOLLOWS_THRESHOLD ]
    return follower_list

def merge_results(*args):
    return list(it.chain(*args))


# vote activity sub-query
votes_stmt = select([votes_tbl.c.voter])\
    .where(votes_tbl.c.voter == accounts_tbl.c.new_account_name)\
    .group_by(votes_tbl.c.voter)\
    .having(func.count(votes_tbl.c.voter) <= EXCLUSIVE_VOTES_THRESHOLD)


# comment activity sub-query
comments_stmt = select([comments_tbl.c.author])\
    .where(comments_tbl.c.author == accounts_tbl.c.new_account_name)\
    .group_by(comments_tbl.c.author)\
    .having(func.count(comments_tbl.c.author) <= EXCLUSIVE_COMMENTS_THRESHOLD)


# minimum account age
min_datetime = datetime.utcnow() - timedelta(days=MIN_ACCOUNT_AGE_DAYS)


main_query = select([accounts_tbl.c.new_account_name])\
    .where(and_(
        accounts_tbl.c.timestamp <= min_datetime,
        accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR,
        accounts_tbl.c.new_account_name.in_(union_all(votes_stmt, comments_stmt))
    ))


# seperate query for followers, slow due to json parsing
follows_query = select([func.json_extract(follows_tbl.c.json, '$.follower').label('follower')]) \
    .where(follows_tbl.c.tid == 'follow')







