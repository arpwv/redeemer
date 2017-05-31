# coding=utf-8
import logging
from datetime import datetime
from datetime import timedelta
import argparse
import asyncio

import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy import select, and_, text
import aiomysql.sa

logger = logging.getLogger('__name__')

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


'''
SELECT sbds_tx_comments.author,
  COUNT(sbds_tx_comments.author) AS comment_count,
  COUNT(sbds_tx_votes.voter) AS vote_count
  FROM sbds_tx_comments
JOIN sbds_tx_account_create_with_delegations ON sbds_tx_comments.author = sbds_tx_account_create_with_delegations.new_account_name
JOIN sbds_tx_votes ON sbds_tx_comments.author = sbds_tx_votes.voter
  WHERE sbds_tx_account_create_with_delegations.creator = 'steem'
GROUP BY sbds_tx_comments.author
HAVING comment_count <= 2 OR vote_count <= 2;
'''

def select_delegation_accounts(db_url):
    engine = sa.create_engine(db_url)
    meta = sa.MetaData()
    meta.reflect(bind=engine)
    accounts_tbl = meta.tables[ACCOUNTS_TABLE]
    votes_tbl = meta.tables[VOTES_TABLE]
    comments_tbl = meta.tables[COMMENTS_TABLE]
    follows_tbl = meta.tables[FOLLOWS_TABLE]

    with engine.connect() as conn:
        query = select([
            comments_tbl.c.author,
            func.count(comments_tbl.c.author).label('comment_count'),
            func.count(votes_tbl.c.voter).label('vote_count')
        ])

        # joins
        query = query.join(accounts_tbl, comments_tbl.c.author ==  accounts_tbl.c.new_account_name)
        query = query.join(votes_tbl, comments_tbl.c.author == votes_tbl.c.voter)

        # where clauses
        query = query.where(accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR)

        min_datetime = datetime.utcnow() - timedelta(days=MIN_ACCOUNT_AGE_DAYS)
        query = query.where(accounts_tbl.c.timestamp <= min_datetime)

        # group by
        query = query.group_by(comments_tbl.c.author)

        # aggregate filter having clauses
        comment_having_clause = 'comment_count <= %s' % EXCLUSIVE_COMMENTS_THRESHOLD
        vote_having_clause = 'vote_count <= %s' % EXCLUSIVE_VOTES_THRESHOLD
        query = query.having(and_(
                comment_having_clause,
                vote_having_clause
        ))

        accounts = conn.execute(query).fetchall()

        query2 = select([
            func.json_extract(follows_tbl.c.json, '$.follower').label('follower')
        ]).where(follows_tbl.c.tid == 'follow')










if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="redeemer de-delegation utility")
    parser.add_argument('--database_url', type=str, default='sqlite:/')
    args = parser.parse_args(argv)