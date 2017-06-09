#! /usr/bin/env python3
# coding=utf-8
import os

import json
from collections import namedtuple
import itertools as it
import logging
import statistics

import sqlalchemy as sa

from sqlalchemy import select, and_
from terminaltables import AsciiTable

import http_client

# steemd tools
from steem import Steem
import steem.converter
from steembase import operations
from steem.amount import Amount

logger = logging.getLogger(__name__)

# python steem
steem_client = Steem(nodes=['https://steemd.steemit.com'], no_broadcast=True)
converter = steem.converter.Converter()

# steemd client
client = http_client.SimpleSteemAPIClient()

# sbds sql config
ACCOUNTS_TABLE = 'sbds_tx_account_create_with_delegations'

# de-delegation config
DELEGATION_ACCOUNT_CREATOR = 'steem'
DELEGATION_ACCOUNT_WIF = None
INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 5 # in sp
INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = Amount('%s VESTS' % int(converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)))
TRANSACTION_EXPIRATION = 60 * 60 * 24 # 1 day

# db config
DB_URL = os.environ['DATABASE_URL']
DB_ENGINE = sa.create_engine(DB_URL,
                          server_side_cursors=True,
                          encoding='utf8',
                          echo=False,
                          execution_options=dict(stream_results=True))



OperationMetric = namedtuple('OperationMetric', ['name',
                                     'vests_to_undelegate',
                                     'op_vesting_shares',
                                     'acct_vests',
                                     'delegated_vests',
                                     'beginning_balance',
                                     'ending_balance',
                                     'ending_delegated'
                                           ])


# ----------------------
# Utility Functions
# ----------------------
def run_query(engine, query):
    with engine.connect() as conn:
        results = conn.execute(query).fetchall()
    return results


def chunkify(iterable, chunksize=10000):
    i = 0
    chunk = []
    for item in iterable:
        chunk.append(item)
        i += 1
        if i == chunksize:
            yield chunk
            i = 0
            chunk = []
    if len(chunk) > 0:
        yield chunk


def print_table(*args, **kwargs):
    tbl = AsciiTable(*args, **kwargs)
    print()
    print(tbl.table)
    print()


def get_steemd_accounts(accounts):
    groups = chunkify(accounts, 100)
    grouped_accounts = []
    for group in groups:
        grouped_accounts.append(client.exec('get_accounts', list(group)))
    return list(it.chain.from_iterable(grouped_accounts))


def compute_undelegation_ops(accounts):
    # remove all but 5, or leave all
    op_metrics = []
    steem_ops = []
    for acct in accounts:
        name = acct['name']
        acct_vests = Amount(acct['vesting_shares'])
        delegated_vests = Amount(acct['received_vesting_shares'])
        beginning_balance = acct_vests + delegated_vests

        # nothing there
        if delegated_vests == 0:
            continue

        vests_to_undelegate = beginning_balance - INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS

        # cant undelegate amount greater than current delegation
        if vests_to_undelegate > delegated_vests:
            vests_to_undelegate = delegated_vests

        ending_delegated = delegated_vests - vests_to_undelegate

        # amount to specify in delegation operation
        op_vesting_shares = delegated_vests - vests_to_undelegate

        # check limit
        ending_balance = beginning_balance - vests_to_undelegate
        assert ending_balance >= INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS

        steem_ops.append(operations.DelegateVestingShares(
                delegator=DELEGATION_ACCOUNT_CREATOR,
                vesting_shares=str(op_vesting_shares),
                delegatee=name
        ))
        op_metrics.append(OperationMetric(name,
                                   vests_to_undelegate,
                                   op_vesting_shares,
                                   acct_vests,
                                   delegated_vests,
                                   beginning_balance,
                                   ending_balance,
                                   ending_delegated))
    return op_metrics, steem_ops

# ----------------------
# Main Program Functions
# ----------------------

# step 1
def get_account_names_from_db():
    # collect account names with delegations
    try:
        with open('accounts.json') as f:
            accounts = json.load(f)
    except:
        meta = sa.MetaData()
        meta.reflect(bind=DB_ENGINE)
        accounts_tbl = meta.tables[ACCOUNTS_TABLE]
        all_accounts_query = select([accounts_tbl.c.new_account_name]) \
            .where(and_(
                accounts_tbl.c.creator == DELEGATION_ACCOUNT_CREATOR,
                accounts_tbl.c.delegation > 0
        ))
        results = run_query(DB_ENGINE, all_accounts_query)
        accounts = [row[0] for row in results]
        with open('accounts.json', 'w') as f:
            json.dump(accounts, f)

    return accounts


# step 2
def get_steem_accounts_from_names(account_names):
    # get accounts from account names
    try:
        with open('steem_accounts.json') as f:
            steemd_accounts = json.load(f)
    except:
        steemd_accounts = get_steemd_accounts(account_names)
        with open('steem_accounts.json','w') as f:
            json.dump(steemd_accounts, f)
    return steemd_accounts


# step 3
def get_undelegation_ops(steemd_accounts):
    # compute undelegation operations
    ops, steem_ops = compute_undelegation_ops(steemd_accounts)
    with open('delegation_ops.json', 'w') as f:
        json.dump([op.json() for op in steem_ops], f)
    return ops, steem_ops


# step 4
def show_undelegation_stats(op_metrics):
    print('min acct balance after undelegation %s SP (%s)' % (
    INCLUSIVE_LOWER_BALANCE_LIMIT_SP, INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS))

    table_data = [
        ['undelegation ops', len(op_metrics)],
        ['complete undelegations ops', len([op for op in op_metrics if op.op_vesting_shares == 0])],
        ['partial undelegations ops', len([op for op in op_metrics if op.op_vesting_shares > 0])]
    ]
    print_table(table_data=table_data, title='Undelegation Op Stats')

    total_vests_to_undelegate = sum(int(op.vests_to_undelegate) for op in op_metrics)
    mean_vests_to_undelegate = statistics.mean(int(op.vests_to_undelegate) for op in op_metrics)
    median_vests_to_undelegate = statistics.median(int(op.vests_to_undelegate) for op in op_metrics)
    try:
        mode_vests_to_undelegate = statistics.mode(int(op.vests_to_undelegate) for op in op_metrics)
    except Exception as e:
        mode_vests_to_undelegate = 'n/a'

    table_data = [
        ['Metric','VESTS', 'SP'],
        ['total to be undelegated', total_vests_to_undelegate],
        ['mean to be undelegated', mean_vests_to_undelegate],
        ['median to be undelegated', median_vests_to_undelegate],
        ['mode to be undelegated', mode_vests_to_undelegate],
    ]

    for row in table_data[1:]:
        row.append(converter.vests_to_sp(row[1]))

    print_table(table_data=table_data, title='Undelegation Stats')

    # before/after stats
    mean_acct_balance_before = statistics.mean(
            int(op.beginning_balance) for op in op_metrics)
    median_acct_balance_before = statistics.median(
            int(op.beginning_balance) for op in op_metrics)


    mean_acct_balance_after = statistics.mean(
            int(op.ending_balance) for op in op_metrics)
    median_acct_balance_after = statistics.median(
            int(op.ending_balance) for op in op_metrics)

    mean_delegated_before =  statistics.mean(int(op.delegated_vests) for op in op_metrics)

    median_delegated_before = statistics.median(int(op.delegated_vests) for op in op_metrics)

    mean_delegated_after = statistics.mean(
            int(op.ending_delegated) for op in op_metrics)

    median_delegated_after = statistics.median(
            int(op.ending_delegated) for op in op_metrics)

    min_delegated_before = min(int(op.delegated_vests) for op in op_metrics)
    min_delegated_after = min(int(op.ending_delegated) for op in op_metrics)

    count_zero_delegated_before = len([op for op in op_metrics if op.delegated_vests == 0])
    count_zero_delegated_after = len([op for op in op_metrics if op.ending_delegated == 0])
    table_data = [
        ['Metric','Before', 'After'],
        ['min acct balance', min(int(op.beginning_balance) for op in op_metrics), min(int(op.ending_balance) for op in op_metrics)],
        ['mean acct balance', mean_acct_balance_before, mean_acct_balance_after],
        ['median acct balance', median_acct_balance_before, median_acct_balance_after],
        ['count accts w/min balance',
         len([op for op in op_metrics if op.beginning_balance == INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS]),
         len([op for op in op_metrics if op.ending_balance == INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS])],
        ['min delegated', min_delegated_before, min_delegated_after],
        ['mean delegated', mean_delegated_before, mean_delegated_after],
        ['median delegated', median_delegated_before, median_delegated_after],
        ['count accts w/zero delegation',count_zero_delegated_before, count_zero_delegated_after ]
    ]
    print_table(table_data=table_data, title='Before/After Acct Stats')


def main():
    print('getting list of accounts from db, be patient...')
    accounts = get_account_names_from_db()

    print('getting accounts from steemd, be patient...')
    steemd_accounts = get_steem_accounts_from_names(accounts)

    print('computing undelegation ops...')
    ops, steem_ops = get_undelegation_ops(steemd_accounts)

    show_undelegation_stats(ops)
    return ops, steem_ops


if __name__ == '__main__':
    main()