# coding=utf-8
import os

from collections import namedtuple
from datetime import datetime
from datetime import timedelta
import itertools as it
import logging
import statistics

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy import select, and_, text, union_all, alias
from sqlalchemy import cast, Integer

import maya
from terminaltables import AsciiTable

import http_client

# steemd tools
from steem import Steem
import steem.converter
from steem.transactionbuilder import TransactionBuilder
from steembase import operations

logger = logging.getLogger(__name__)

# python steem
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
MIN_ACCOUNT_AGE_DAYS = 0
INCLUSIVE_VOTES_THRESHOLD = 2
INCLUSIVE_COMMENTS_THRESHOLD = 2
INCLUSIVE_POSTS_THRESHOLD = 2
INCLUSIVE_FOLLOWS_THRESHOLD = 0
INCLUSIVE_MAX_CREATION_DATE = datetime.utcnow() - timedelta(days=MIN_ACCOUNT_AGE_DAYS)

INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 5 # in sp
INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)


# db config
db_url = os.environ['DATABASE_URL']
engine = sa.create_engine(db_url,
                          server_side_cursors=True,
                          encoding='utf8',
                          echo=False,
                          execution_options=dict(stream_results=True))
meta = sa.MetaData()
meta.reflect(bind=engine)
accounts_tbl = meta.tables[ACCOUNTS_TABLE]
votes_tbl = meta.tables[VOTES_TABLE]
comments_tbl = meta.tables[COMMENTS_TABLE]
follows_tbl = meta.tables[FOLLOWS_TABLE]


Operation = namedtuple('Operation', ['account', 'undelegate_vests', 'op_vesting_shares'])


# functions used below
def run_query(engine, query):
    with engine.connect() as conn:
        results = conn.execute(query).fetchall()
    return results


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

def print_table(*args, **kwargs):
    tbl = AsciiTable(*args, **kwargs)
    print()
    print(tbl.table)
    print()


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
        if undelegate_vests >= delegated_vests:
            undelegate_vests = delegated_vests
        op_vesting_shares = delegated_vests - undelegate_vests
        ops.append(Operation(acct, undelegate_vests, op_vesting_shares))
        new_balance = acct_vests + delegated_vests - undelegate_vests
        logger.debug('OPERATION: %s delegated %s --> undelegate %s VESTS --> new balance %s VESTS', name, delegated_vests,undelegate_vests, new_balance)
        assert new_balance >= INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS

    return ops


def perform_undelegation_ops(ops, no_broadcast=False):
    successes = []
    fails = []
    for op in ops:
        try:
            tb = TransactionBuilder(no_broadcast=no_broadcast)
            steem_op = {
                'to_account':op.account['name'],
                'vesting_shares': op.op_vesting_shares,
                'account': DELEGATION_ACCOUNT_CREATOR
            }
            steem_op = operations.DelegateVestingShares(**steem_op)
            print(steem_op)
            tb.appendOps([steem_op])
            tb.appendSigner(DELEGATION_ACCOUNT_CREATOR, 'active')
            tb.sign()
            tx = tb.broadcast()
            print(tx)
        except Exception as e:
            logger.debug(e)
            fails.append(op)
        else:
            successes.append(op)

    return successes, fails



# collect account names with delegations
all_accounts_query = select([accounts_tbl.c.new_account_name]) \
    .where(and_(
        accounts_tbl.c.timestamp <= INCLUSIVE_MAX_CREATION_DATE,
        accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR,
        accounts_tbl.c.delegation > 0
))
print('querying db for accounts, be patient...')
results = run_query(engine, all_accounts_query)
accounts = [row[0] for row in results]

# get accounts from account names
steemd_accounts = get_steemd_accounts(accounts)

# filter accounts

print('filtering accounts...')
print('filter accounts with no delegations')
before = len(steemd_accounts)
filtered_accounts = list(filter_zero_delegations(steemd_accounts))
after = len(filtered_accounts)
table_data=[
    ['before','after'],
    [before, after]
]
print_table(table_data=table_data, title='Filter Results')


# compute undelegation operations
print('computing undelegation ops...')
ops = compute_undelegation_ops(filtered_accounts)

print('total undelegation operations: %s' % len(ops))

total_undelegated_vests = sum(op[1] for op in ops)
total_undelegated_sp = converter.vests_to_sp(total_undelegated_vests)
mean_undelegation_vests = statistics.mean(op[1] for op in ops)
median_undelegation_vests = statistics.median(op[1] for op in ops)
mean_undelegation_sp = converter.vests_to_sp(mean_undelegation_vests)
median_undelegation_sp = converter.vests_to_sp(median_undelegation_vests)

table_data = [
    ['Metric','VESTS', 'SP'],
    ['total undelegated', total_undelegated_vests, total_undelegated_sp],
    ['mean undelegated', mean_undelegation_vests, mean_undelegation_sp],
    ['median undelegated', median_undelegation_vests, median_undelegation_sp]
]
print_table(table_data=table_data, title='To Be Un-Delegated Metrics')


# build and broadcast undelegation operations
NO_BROADCAST_TRANSACTIONS = False
successes, fails = perform_undelegation_ops(ops, no_broadcast=NO_BROADCAST_TRANSACTIONS)
table_data = [
    ['result','percent', 'count'],
    ['success',len(successes)/len(ops)*100, len(successes)],
    ['fail', len(fails)/len(ops)*100, len(fails)]
 ]
print_table(table_data=table_data, title='Broadcast Results')
