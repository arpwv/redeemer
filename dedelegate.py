#! /usr/bin/env python3
# coding=utf-8
import configargparse
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

logger = logging.getLogger(__name__)

# config-prep
STEEMD_NODES = ['https://api.steemit.com']
steemd = Steem(nodes=STEEMD_NODES)
steem.instance.set_shared_steemd_instance(steemd)
chain_props = steemd.get_chain_properties()
account_creation_fee = Amount(chain_props['account_creation_fee']).amount
converter = steem.converter.Converter()

# de-delegation config
DELEGATION_ACCOUNT_CREATOR = 'steem'
DELEGATION_ACCOUNT_WIF = None
INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 15
TRANSACTION_EXPIRATION = 60 # 1 min
STEEM_PER_VEST = steem.converter.Converter().steem_per_mvests() / 1e6
INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = Amount('%s VESTS' % int(converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)))

# min_update: https://github.com/steemit/steem/blob/56c4d8991622541381df4658bae4b90157690bf4/libraries/chain/steem_evaluator.cpp#L2179
MIN_UPDATE = converter.sp_to_vests(account_creation_fee)
MIN_DELEGATION = MIN_UPDATE * 10

STEEMIT_MAX_BLOCK_SIZE = int(chain_props['maximum_block_size'])
MAX_OPS_GROUP_SIZE = int(STEEMIT_MAX_BLOCK_SIZE / 16)


OperationMetric = namedtuple('OperationMetric', ['name',
                                     'delegation_type',
                                     'vests_to_delegate',
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


def group_ops(ops, max_size=MAX_OPS_GROUP_SIZE, max_len=300):
    group_size = 0
    group = []
    for op in ops:
        op_size = len(json.dumps(op))
        if group_size + op_size > max_size or len(group) == max_len:
            yield group
            group = [op]
            group_size = op_size
        else:
            group.append(op)
            group_size += op_size
    yield group


def compute_delegation_ops(accounts, delegation_type=None):
    op_metrics = []
    steem_ops = []
    for acct in accounts:
        name = acct['name']
        acct_vests = Amount(acct['vesting_shares'])
        delegated_vests = Amount(acct['received_vesting_shares'])
        beginning_balance = acct_vests + delegated_vests
        vests_to_delegate = INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS - beginning_balance

        # cant undelegate amount greater than current delegation
        if vests_to_delegate < 0 and abs(float(vests_to_delegate)) > delegated_vests:
            vests_to_delegate =  -1.0 * float(delegated_vests)
            vests_to_delegate = Amount('%s VESTS' % vests_to_delegate)

        # skip delegations less than minimum_update
        if abs(float(vests_to_delegate)) < MIN_UPDATE:
            continue

        if vests_to_delegate < 0:
            delegation_type = 'undelegation'
        elif vests_to_delegate > 0:
            delegation_type = 'delegation'
        elif vests_to_delegate == 0:
            continue
        else:
            raise ValueError(vests_to_delegate)

        # optionally ignore a certain delegation_type
        if delegation_type != delegation_type:
            continue

        ending_delegated = delegated_vests + vests_to_delegate

        # amount to specify in delegation operation
        op_vesting_shares = delegated_vests + vests_to_delegate

        # skip delegations less than minimum_delegation
        if op_vesting_shares < MIN_DELEGATION:
            continue


        ending_balance = beginning_balance + vests_to_delegate

        try:
            # sanity checks

            # never delegate more than min
            assert op_vesting_shares <= INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS

            # no action leaves anyone with less than min
            assert ending_balance >= INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS

            # no updates less then min_update
            assert abs(float(op_vesting_shares - delegated_vests)) >= MIN_UPDATE

            assert op_vesting_shares >= MIN_DELEGATION

            # no action undelegates more than delegation
            if delegation_type == 'undelegation':
                assert delegated_vests > 0
                assert abs(float(vests_to_delegate)) <= delegated_vests
            
            if delegation_type == 'delegation':
                pass
            
        except AssertionError as e:
            logger.exception('error %s, %s', e, OperationMetric(name,
                                              delegation_type,
                                              vests_to_delegate,
                                              op_vesting_shares,
                                              acct_vests,
                                              delegated_vests,
                                              beginning_balance,
                                              ending_balance,
                                              ending_delegated))
            continue

        steem_ops.append(operations.DelegateVestingShares(
                    delegator=DELEGATION_ACCOUNT_CREATOR,
                    vesting_shares=str(op_vesting_shares),
                    delegatee=name
            ).json())
        op_metrics.append(OperationMetric(name,
                                              delegation_type,
                                              vests_to_delegate,
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
def get_accounts_from_steemd(account='steem', max_accounts=100000000, batch_size=10000):
    steem = Steem(nodes=STEEMD_NODES, no_broadcast=True)
    total_transactions_in_account = steem.get_account_history(account,-1,1)[0][0]
    logger.info('total transactions for %s account to review: %s', account, total_transactions_in_account)
    offset = -1

    results_count = 0
    offset_path = (0,0)
    op_path = (1,'op',0)
    account_path = (1,'op',1,'new_account_name')
    while True:
        logger.info('result count: %s offset:%s',results_count, offset)
        try:
            r = steem.get_account_history(account, offset, batch_size)
            results_count += len(r)
            ops = filter(lambda o: get_in(op_path,o)=='account_create_with_delegation', r)
            account_names = [get_in(account_path,o) for o in ops]
            logger.debug('filtered %s ops to %s account names', batch_size, len(account_names))
            logger.debug('fetching %s accounts from steemd', len(account_names))
            if account_names:
                accounts = steem.get_accounts(account_names)
                if not accounts:
                    continue
                yield accounts
            if results_count >= max_accounts:
                break
            offset = get_in(offset_path, r) - 1
            if offset <= 1:
                break
            if offset < batch_size:
                offset = batch_size
        except Exception as e:
            logger.exception('Ignoring this error')

# step 2
def get_delegation_ops(steemd_accounts, delegation_type=None):
    # compute undelegation operations
    op_metrics, steem_ops = compute_delegation_ops(steemd_accounts, delegation_type=delegation_type)
    with open('%s_ops.json' % delegation_type,'w') as f:
        json.dump(steem_ops, f)
    return op_metrics, steem_ops



# step 3
def show_delegation_stats(op_metrics, delegation_type=None):
    print('min acct balance after delegation %s SP (%s)' % (
    INCLUSIVE_LOWER_BALANCE_LIMIT_SP, INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS))

    table_data = [
        ['delegation ops', len([o for o in op_metrics if o.delegation_type == 'delegation'])],
        ['undelegation ops', len([o for o in op_metrics if o.delegation_type == 'undelegation'])],
        ['complete undelegations ops', len([op for op in op_metrics if op.op_vesting_shares == 0])],
        ['partial undelegations ops', len([op for op in op_metrics if op.op_vesting_shares > 0])]
    ]
    print_table(table_data=table_data, title='%s Op Stats' % delegation_type.title())

    total_vests_to_delegate = sum(int(op.vests_to_delegate) for op in op_metrics)
    mean_vests_to_delegate = statistics.mean(int(op.vests_to_delegate) for op in op_metrics)
    median_vests_to_delegate = statistics.median(int(op.vests_to_delegate) for op in op_metrics)
    try:
        mode_vests_to_delegate = statistics.mode(int(op.vests_to_delegate) for op in op_metrics)
    except Exception as e:
        mode_vests_to_delegate = 'n/a'

    verb = 'undelegated'
    if delegation_type == 'delegation':
        verb = 'delegated'

    table_data = [
        ['Metric','VESTS', 'SP'],
        ['total to be %s' % verb, total_vests_to_delegate],
        ['mean to be %s' % verb, mean_vests_to_delegate],
        ['median to be %s' % verb, median_vests_to_delegate],
        ['mode to be %s' % verb, mode_vests_to_delegate],
    ]

    for row in table_data[1:]:
        row.append(converter.vests_to_sp(row[1]))

    print_table(table_data=table_data, title='%s Stats' % delegation_type.title())

    # before/after stats
    mean_acct_balance_before = statistics.mean(
            int(op.beginning_balance) for op in op_metrics)
    median_acct_balance_before =  statistics.median(
            int(op.beginning_balance) for op in op_metrics)


    mean_acct_balance_after =  statistics.mean(
            int(op.ending_balance) for op in op_metrics)
    median_acct_balance_after =  statistics.median(
            int(op.ending_balance) for op in op_metrics)

    mean_delegated_before =   statistics.mean(int(op.delegated_vests) for op in op_metrics)

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



def build_and_sign(ops=None,key=None, no_broadcast=True, signing_start=None, expiration=TRANSACTION_EXPIRATION):
    from steem.transactionbuilder import TransactionBuilder
    from steembase import operations
    if key:
        s = Steem(nodes=STEEMD_NODES, no_broadcast=no_broadcast, keys=[key], debug=True)
    else:
        s = Steem(nodes=STEEMD_NODES, no_broadcast=no_broadcast, keys=[None], debug=True)

    for group_num, op_group in enumerate(group_ops(ops)):
        error_count = 0
        start_op_index = ops.index(op_group[0]) + signing_start
        end_op_index = ops.index(op_group[-1]) + signing_start
        logger.debug('group:%s start:%s end:%s', group_num, start_op_index, end_op_index)
        while True:
            group_size = len(json.dumps(op_group))
            group_len = len(op_group)
            try:
                tx = TransactionBuilder(steemd_instance=s, no_broadcast=no_broadcast, expiration=expiration)
                tx.appendOps([operations.DelegateVestingShares(**op) for op in op_group])
                tx.appendSigner(DELEGATION_ACCOUNT_CREATOR, 'active')
                if key:
                    tx.sign()
                    if not no_broadcast:
                        result = tx.broadcast()
                        logger.debug('broadcasted group:%s start:%s end:%s len:%s size:%s result:%s',
                                     group_num, start_op_index, end_op_index, group_len,
                                     group_size, result)
                    else:
                        logger.debug('skipping broadcast of tx because no_broadcast=%s', no_broadcast)
                else:
                    logger.warn('skipping signing of tx because no key provided')
                print(json.dumps(tx))
                break
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except Exception as e:
                error_count += 1
                logger.exception('Error while broadcasting')

                if error_count == 3:
                    with open('error_%s_ops_start_%s_end%s.json' % (group_num, start_op_index, end_op_index), 'w') as f:
                        json.dump(op_group, f)
                    with open('error_%s.txt' % group_num, 'w') as f:
                        f.write('%s' % e.__repr__())
                    break


def main(delegation_type='undelegation',key=None, ops=None, show_stats=False, no_broadcast=True, signing_start=0):
    if not ops:
        logger.info('getting accounts from steemd, be patient...')
        steemd_accounts = it.chain.from_iterable(get_accounts_from_steemd())

        logger.info('computing undelegation ops...')
        op_metrics, ops = get_delegation_ops(steemd_accounts, delegation_type=delegation_type)

        if show_stats:
            show_delegation_stats(op_metrics, delegation_type=delegation_type)

    logger.info('building and signing transactions...')
    build_and_sign(ops=ops, key=key, no_broadcast=no_broadcast, signing_start=signing_start)


if __name__ == '__main__':

    parser = configargparse.ArgumentParser('redeemer', formatter_class=configargparse.ArgumentDefaultsRawHelpFormatter)
    parser.add_argument('--delegation_type', type=str, help='The type of delegation to perform.', default='undelegation')
    parser.add_argument('--wif', type=configargparse.FileType('r'), help='The flag expects a path to a file. The environment variable REDEEMER_WIF will be checked for a literal WIF also.')
    parser.add_argument('--ops', type=configargparse.FileType('r'))
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--no_broadcast', action='store_true')
    parser.add_argument('--signing_start_index', type=int, default=0)
    parser.add_argument('--log_level', type=str, default='INFO')

    args = parser.parse_args()

    logging.basicConfig(level=logging.getLevelName(args.log_level))

    wif = None
    if args.wif:
        logger.info('Using wif from file %s' % args.wif)
        wif = args.wif.read().strip()
    elif os.environ.get('REDEEMER_WIF') is not None:
        logger.info('Using wif from environment variable REDEEMER_WIF')
        wif = os.environ.get('REDEEMER_WIF')
    else:
        logger.warn('You have not specified a wif; signing transactions is not possible!')

    if args.ops:
        ops = json.load(args.ops)
    else:
        ops = args.ops
    main(delegation_type=args.delegation_type,
         key=wif,
         ops=ops,
         show_stats=args.stats,
         no_broadcast=args.no_broadcast,
         signing_start=args.signing_start_index)
