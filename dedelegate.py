#! /usr/bin/env python3
# coding=utf-8
import argparse
import os
import json
import itertools as it
import logging
import statistics
import sys

from collections import namedtuple

from terminaltables import AsciiTable
from toolz.dicttoolz import get_in

# steemd tools
from steem import Steem
import steem.converter
from steembase import operations
from steem.amount import Amount

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


converter = steem.converter.Converter()

# de-delegation config
DELEGATION_ACCOUNT_CREATOR = 'steem'
DELEGATION_ACCOUNT_WIF = None
INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 15 # in sp
INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = Amount('%s VESTS' % int(converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)))
TRANSACTION_EXPIRATION = 60 * 60 * 24 # 1 day
OPS_PER_TRANSACTION = 100
STEEMD_NODES = ['https://steemd.steemit.com']




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


def compute_undelegation_ops(accounts):
    # remove all but INCLUSIVE_LOWER_BALANCE_LIMIT_SP, or leave all
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
def get_accounts_from_steemd(account='steem'):
    steem = Steem(nodes=STEEMD_NODES, no_broadcast=True)
    total_transactions_in_account = steem.get_account_history(account,-1,1)[0][0]
    logger.debug('total transactions for %s account to review: %s', account, total_transactions_in_account)
    offset = -1
    limit = 10000
    results_count = 0
    offset_path = (0,0)
    op_path = (1,'op',0)
    account_path = (1,'op',1,'new_account_name')
    while True:
        logger.debug('result count: %s offset:%s',results_count, offset)
        try:
            r = steem.get_account_history(account, offset, limit)
            results_count += len(r)
            ops = filter(lambda o: get_in(op_path,o)=='account_create_with_delegation', r)
            account_names = [get_in(account_path,o) for o in ops]
            logger.debug('filtered %s ops to %s account names', limit, len(account_names))
            logger.debug('fetching %s accounts from steemd', len(account_names))
            if account_names:
                accounts = steem.get_accounts(account_names)
                if not accounts:
                    continue
                yield accounts
            offset = get_in(offset_path, r) - 1
            if offset <= 1:
                break
            if offset < limit:
                offset = limit
        except Exception as e:
            logger.exception('Ignoring this error')

# step 2
def get_undelegation_ops(steemd_accounts):
    # compute undelegation operations
    ops, steem_ops = compute_undelegation_ops(steemd_accounts)
    with open('delegation_ops.json', 'w') as f:
        json.dump([op.json() for op in steem_ops], f)
    return ops, steem_ops


# step 3
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


def build_and_sign(ops=None, key=None, chunksize=OPS_PER_TRANSACTION, no_broadcast=True):
    from steem.transactionbuilder import TransactionBuilder
    from steembase import operations
    if key:
        s = Steem(nodes=STEEMD_NODES, no_broadcast=no_broadcast, keys=[key],debug=True)
    else:
        s = Steem(nodes=STEEMD_NODES, no_broadcast=no_broadcast, keys=[], debug=True)
    for i,chunk in enumerate(chunkify(ops, chunksize=chunksize)):
        tx = TransactionBuilder(steemd_instance=s, no_broadcast=no_broadcast)
        while True:
            try:
                tx.appendOps([operations.DelegateVestingShares(**op) for op in chunk])
                tx.appendSigner('steem','active')
                tx.sign()
                print(json.dumps(tx))
                if not no_broadcast:
                    tx.broadcast()
                    logger.debug('broadcasted tx #%s',i)
                break
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except Exception as e:
                logger.exception('Ignored this error')



def main(key=None, ops=None, show_stats=False, no_broadcast=True):
    if not ops:
        print('getting accounts from steemd, be patient...')
        steemd_accounts = it.chain.from_iterable(get_accounts_from_steemd())

        print('computing undelegation ops...')
        ops, steem_ops = get_undelegation_ops(steemd_accounts)

    if show_stats:
        show_undelegation_stats(ops)

    build_and_sign(ops=ops,key=key,no_broadcast=no_broadcast)



if __name__ == '__main__':

    parser = argparse.ArgumentParser('Steemit de-delegation script')
    parser.add_argument('--wif', type=argparse.FileType('r'))
    parser.add_argument('--ops', type=argparse.FileType('r'))
    parser.add_argument('--stats', type=bool, default=False)
    parser.add_argument('--no_broadcast', type=bool, default=True)
    args = parser.parse_args()
    if args.ops:
        ops = json.load(args.ops)
    else:
        ops = args.ops
    main(key=args.wif,
         ops=ops,
         show_stats=args.stats,
         no_broadcast=args.no_broadcast)