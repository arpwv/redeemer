# coding=utf-8
import os
import json
from collections import Counter
from datetime import datetime
from datetime import timedelta
import itertools as it
import time
import decimal
import statistics

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy import select, and_, text, union_all, alias

import maya

import http_client

# steemd tools
from steem import Steem
import steem.converter
steem_client = Steem(nodes=['https://steemd.steemit.com'])
converter = steem.converter.Converter()


# steemd client
client = http_client.SimpleSteemAPIClient()

# sbds sql config
ACCOUNTS_TABLE = 'sbds_tx_account_create_with_delegations'
VOTES_TABLE = 'sbds_tx_votes'
COMMENTS_TABLE = 'sbds_tx_comments'
FOLLOWS_TABLE = 'sbds_tx_custom_jsons'

# de-delegation config
DELEGATION_ACCOUNT_CREATOR = 'steem'
MIN_ACCOUNT_AGE_DAYS = 30
INCLUSIVE_VOTES_THRESHOLD = 2
INCLUSIVE_COMMENTS_THRESHOLD = 2
INCLUSIVE_POSTS_THRESHOLD = 2
INCLUSIVE_FOLLOWS_THRESHOLD = 0
INCLUSIVE_MAX_CREATION_DATE = datetime.utcnow() - timedelta(days=MIN_ACCOUNT_AGE_DAYS)

INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 5 # in sp
INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)


# steemd account filters
STEEMD_ACCOUNT_FILTERS = {
    'lifetime_vote_count': INCLUSIVE_VOTES_THRESHOLD,
    'comment_count': INCLUSIVE_COMMENTS_THRESHOLD,
    'post_count': INCLUSIVE_COMMENTS_THRESHOLD,
    'received_vesting_shares': "0.000000 VESTS",
}

# db config
db_url = os.environ['DATABASE_URL']
engine = sa.create_engine(db_url,
                          server_side_cursors=True,
                          encoding='utf8',
                          echo=True,
                          execution_options=dict(stream_results=True))
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

def get_account_names(engine, query):
    results = run_query(engine, query)
    return map(get_steemd_accounts, (r[0] for r in results))

def merge_results(*args):
    return list(it.chain(*args))

def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return it.zip_longest(*args, fillvalue=fillvalue)

def get_steemd_accounts(accounts):
    groups = grouper(accounts, 10)
    grouped_accounts = []
    for group in groups:
        grouped_accounts.append(client.exec('get_accounts', list(group)))
    return list(it.chain.from_iterable(grouped_accounts))


def filter_followers(accounts, limit=INCLUSIVE_FOLLOWS_THRESHOLD):
    for acct in accounts:
        following = steem_client.get_following(acct['name'], acct['name'], 'blog', limit + 1)
        print('acct %s: following: %s' % (acct['name'], following))
        if len(following) <= limit:
            yield acct


def parse_amount(amount_str):
    number, symbol = amount_str.split()
    if '.' in number:
        number = float(number)
    else:
        number = int(number)
    return number, symbol

def filter_zero_delegations(accounts):
    for acct in accounts:
       delegated_vests, _ = parse_amount(acct['received_vesting_shares'])
       if delegated_vests > 0:
           yield acct


def compute_undelegation_ops(accounts):
    # remove all but 5, or leave all
    ops = []
    for acct in accounts:
        name = acct['name']
        acct_vests, _ = parse_amount(acct['vesting_shares'])
        delegated_vests, _ = parse_amount(acct['received_vesting_shares'])

        undelegate_vests = delegated_vests - INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS + acct_vests
        if undelegate_vests > delegated_vests:
            undelegate_vests = delegated_vests

        ops.append(tuple([acct, undelegate_vests]))
        new_balance = acct_vests + delegated_vests - undelegate_vests
        assert new_balance >= INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS
        #print('OPERATION: %s delegated %s --> undelegate %s VESTS --> new balance %s VESTS' % (name, delegated_vests,undelegate_vests, new_balance))
    return ops


# vote activity sub-query
votes_stmt = select([votes_tbl.c.voter])\
    .where(votes_tbl.c.voter == accounts_tbl.c.new_account_name)\
    .group_by(votes_tbl.c.voter)\
    .having(func.count(votes_tbl.c.voter) <= INCLUSIVE_VOTES_THRESHOLD)


# comment activity sub-query
comments_stmt = select([comments_tbl.c.author])\
    .where(comments_tbl.c.author == accounts_tbl.c.new_account_name)\
    .group_by(comments_tbl.c.author)\
    .having(func.count(comments_tbl.c.author) <= INCLUSIVE_COMMENTS_THRESHOLD)

# follows activity sub-query
follows_stmt = select([func.json_unquote(func.json_extract(follows_tbl.c.json, '$.follower')).label('follower')])\
    .where(follows_tbl.c.tid == 'follow')\
    .group_by('follower')\
    .having(and_(
        func.count('follower') <= INCLUSIVE_FOLLOWS_THRESHOLD,
        text('follower') == accounts_tbl.c.new_account_name
    ))


main_query = select([accounts_tbl.c.new_account_name])\
    .where(and_(
        accounts_tbl.c.timestamp <= INCLUSIVE_MAX_CREATION_DATE,
        accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR,
        accounts_tbl.c.new_account_name.in_(union_all(votes_stmt, comments_stmt))
    ))


# seperate query for followers, slow due to json parsing
follows_query = select([func.json_extract(follows_tbl.c.json, '$.follower').label('follower')]) \
    .where(follows_tbl.c.tid == 'follow')\
    .group_by('follower')\
    .having(func.count('follower') <= INCLUSIVE_FOLLOWS_THRESHOLD)

all_accounts_query = select([accounts_tbl.c.new_account_name]) \
    .where(and_(
        accounts_tbl.c.timestamp <= INCLUSIVE_MAX_CREATION_DATE,
        accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR
))

results = run_query(engine, all_accounts_query)

accounts = [row[0] for row in results]

steemd_accounts = get_steemd_accounts(accounts)



print('accounts before zero delegation filter: %s' %  len(steemd_accounts))
filtered_accounts = list(filter_zero_delegations(steemd_accounts))
print('accounts after zero delegation filter filter: %s' % len(filtered_accounts))
print()

print('computing undelegation ops')
ops = compute_undelegation_ops(filtered_accounts)


'''
print('accounts before post_count filter: %s' % len(steemd_accounts))
filtered_accounts = list(filter(lambda a:a['post_count'] <= INCLUSIVE_POSTS_THRESHOLD, steemd_accounts ))
print('accounts after post_count filter: %s' %  len(filtered_accounts))
print()

print('accounts before comment_count filter: %s' %  len(filtered_accounts))
filtered_accounts = list(filter(lambda a:a['comment_count'] <= INCLUSIVE_COMMENTS_THRESHOLD, filtered_accounts))
print('accounts after comment_count filter: %s' %  len(filtered_accounts))
print()

print('accounts before lifetime_vote_count filter: %s' %  len(filtered_accounts))
filtered_accounts = list(filter(lambda a:a['lifetime_vote_count'] <= INCLUSIVE_VOTES_THRESHOLD, filtered_accounts))
print('accounts after lifetime_vote_count filter: %s' %  len(filtered_accounts))
print()

#print('accounts before followers filter: %s' %  len(filtered_accounts))
#filtered_accounts = list(filter_followers(filtered_accounts))
#print('accounts after followers filter filter: %s' % len(filtered_accounts))
#print()

ops = high_balances_ops(filtered_accounts)
'''

print('total undelegation operations: %s' % len(ops))
total_undelegated_vests = sum(op[1] for op in ops)
total_undelegated_sp = converter.vests_to_sp(total_undelegated_vests)
mean_undelegation_vests = statistics.mean(op[1] for op in ops)
median_undelegation_vests = statistics.median(op[1] for op in ops)


mean_undelegation_sp = converter.vests_to_sp(mean_undelegation_vests)
median_undelegation_sp = converter.vests_to_sp(median_undelegation_vests)


print('total undelegation amount: vests:%s sp:%s' % (total_undelegated_vests, total_undelegated_sp))
print('mean undelegation vests: %s sp: %s' % (mean_undelegation_vests, mean_undelegation_sp))
print('median undelegationvests: %s sp: %s' % (median_undelegation_vests, median_undelegation_sp))






