#! /usr/bin/env python3
# coding=utf-8
import argparse
import datetime
import os
import json
import itertools as it
from functools import partial
import logging
import statistics
import tempfile

from enum import Flag

from pathlib import Path
from typing import Tuple
from typing import List
from typing import Optional
from typing import Union
from typing import Iterable
from typing import Generator
from typing import NamedTuple

from collections import namedtuple

import daiquiri
import funcy.seqs
import maya

from terminaltables import AsciiTable
from toolz.dicttoolz import get_in
from funcy.decorators import contextmanager
from funcy.seqs import takewhile
from funcy.seqs import take


# steemd tools
from steem import Steem
from steem.commit import Commit
import steem.converter
from steem.transactionbuilder import TransactionBuilder
from steembase import operations
from steem.amount import Amount
from steembase.exceptions import (
    InsufficientAuthorityError,
    MissingKeyError,
    InvalidKeyFormat
)

daiquiri.setup(level=logging.DEBUG)
logger = daiquiri.getLogger(__name__)

converter = steem.converter.Converter()

# batch sizes
STEEM_ACCOUNT_PAGER_BATCH_SIZE = 5000


# filenames
BASE_DELEGATION_STATS_FILENAME = '%s-%s-delegation_stats.json'
BASE_BROADCASTED_TRANSACTIONS_FILENAME = '%s-%s-broadcasted.json'
BASE_UNPROCESSED_OPS_FILENAME = '%s-%s-unprocessed_ops.json'


# de-delegation config
DELEGATION_ACCOUNT = 'steem'  # type: str
INCLUSIVE_LOWER_BALANCE_LIMIT_SP = 15  # type: int
TRANSACTION_EXPIRATION = 60  # type: int
STEEMD_NODES = ['https://steemd.steemit.com']  # type: List[str]

INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = Amount('%s VESTS' % int(
    converter.sp_to_vests(INCLUSIVE_LOWER_BALANCE_LIMIT_SP)))  # type: Amount
SPAM_INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS = Amount('0 VESTS')

# "account_creation_fee": "0.200 STEEM"
MIN_UPDATE = converter.sp_to_vests(.2)  # type: Amount
SPAM_MIN_UPDATE = Amount('0 VESTS')

MIN_DELEGATION = MIN_UPDATE * 10  # type: Amount
SPAM_MIN_ACCOUNT_DELEGATION = Amount("0 VESTS") # type Amount

# "maximum_block_size": 65536
STEEMIT_MAX_BLOCK_SIZE = 65536  # type: int
MAX_OPS_GROUP_SIZE = int(STEEMIT_MAX_BLOCK_SIZE / 2)  # type: int
MAX_OPS_PER_TRANSACTION = 500

class Delegation(Flag):
    NOOP = 1
    SUB_TO_ZERO = 2
    SUB_TO_MIN = 4
    ADD_TO_MIN = 8
    TO_MIN = ADD_TO_MIN | SUB_TO_MIN

    @classmethod
    def infer_type(cls, vests_to_delegate:Amount, ending_delegated:Amount):
        if vests_to_delegate == 0:
            return cls.NOOP
        elif vests_to_delegate < 0 and ending_delegated == 0:
            return cls.SUB_TO_ZERO
        elif vests_to_delegate < 0 and ending_delegated > 0:
            return cls.SUB_TO_MIN
        elif vests_to_delegate > 0:
            return cls.ADD_TO_MIN
        else:
            raise ValueError(f'Bad delegation: vests_to_delegate:{vests_to_delegate} ending_delegated:{ending_delegated}')

    @property
    def verb(self):
        verbs = {
            1: 'NOOP',
            2: 'Dedelegated To Zero',
            4: 'Dedelegated To Min',
            8: 'Delegated To Min',
            12: '[De]Delegated To Min'
        }
        return verbs[self.value]

class ComputedOperation(NamedTuple):
    delegator: str
    delegatee: str
    delegation_type: Delegation
    vests_to_delegate: Amount
    op_vesting_shares: Amount
    acct_vests: Amount
    delegated_vests: Amount
    beginning_balance: Amount
    ending_balance: Amount
    ending_delegated: Amount

    def json(self):
        return json.dumps(self)

    @classmethod
    def from_json(kls, json_str:str) -> NamedTuple:
        obj = json.loads(json_str, object_hook=lambda f: Amount('%s %s' % (f['amount'], f['asset'])))
        return kls(*obj)

# ----------------------
# Utility Functions
# ----------------------

# cli utilities
def read_json_type(*args, **kwargs):
    with open(*args, **kwargs) as f:
        return json.load(f)

def read_and_strip_text_type(*args, **kwargs):
    with open(*args, **kwargs) as f:
        return f.read().strip()

def readlines_and_strip_text_type(*args, collapse_single=True, **kwargs):
    items = []
    with open(*args, **kwargs) as f:
        for line in f:
            items.append(line.strip())
    if collapse_single and len(items) == 1:
        return items[0]
    else:
        return items

def utc_datetime(datetime_string):
    mdt = maya.parse(datetime_string)
    dt = mdt.datetime()
    logger.debug(f'datetime: {dt}')
    return dt

# program utilities
def chunkify(iterable: Iterable,
             chunksize: int=10000) -> Generator[List, None, None]:
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


def init_results_files(filenames):
    for filename in filenames:
        if not os.path.exists(filename):
            logger.debug('initializing results file %s', filename)
            with open(filename, 'w', encoding='utf8') as f:
                json.dump([], f)


def atomic_append_json(filename:str, new_contents:List[dict], test=True):
    new_contents_len = len(new_contents)
    logger.debug('atomically adding %s ops to %s', len(new_contents), filename)

    with open(filename, 'r', encoding='utf8') as old:
        json_list = json.load(old)
    old_len = len(json_list)
    logger.debug('%s items on list before append', old_len)
    json_list.extend(new_contents)

    logger.debug('%s items on list after append', len(json_list))
    with tempfile.NamedTemporaryFile(delete=False, mode='w') as temp:
        json.dump(json_list, temp)
        temp_name = temp.name
        logger.debug('wrote new list to %s', temp_name)
    if test:
        with open(temp_name, 'r', encoding='utf8') as f:
            test_list = json.load(f)
            assert len(test_list) == new_contents_len + old_len
            logger.debug(
                'confirmed %s items in %s is previous count %s plus new count %s',
                len(test_list), temp_name, old_len, new_contents_len)
    logger.debug('renaming %s to %s', temp_name, filename)
    os.rename(temp_name, filename)


def group_ops(ops: Iterable,
              max_ops_size: int=MAX_OPS_GROUP_SIZE,
              max_ops_count: int=MAX_OPS_PER_TRANSACTION
              ) -> Generator[List, None, None]:
    group_size = 0
    group = []
    for op in ops:
        op_size = len(json.dumps(op))
        if group_size + op_size > max_ops_size or len(group) == max_ops_count:
            yield group
            group = [op]
            group_size = op_size
        else:
            group.append(op)
            group_size += op_size
    if group:
        yield group


def steemd_item_count(func: callable, args):
    item_count = func(*args,-1,1)[0][0]
    logger.debug('Steem.%s(%s) item count: %s', func.__name__, args, item_count)
    return item_count

def steemd_pager(func: callable, *args, start:int=-1, stop:int=0, batch_size:int=STEEM_ACCOUNT_PAGER_BATCH_SIZE):
    logger.debug('steemd_pager(func.__name__=%s, args=%s, start=%s, stop=%s, batch_size=%s)', func.__name__, args, start, stop, batch_size)
    if start == -1:
        item_count = steemd_item_count(func, args)
        start = item_count
        logger.debug('steemd_pager new start=%s', start)
    for offset in range(start, stop, -batch_size):
        logger.debug('steemd_pager offset=%s', offset)
        if offset < batch_size:
            batch_size = offset
            logger.debug('steemd_pager offset < batch_size -> batch_size=%s', batch_size-1)
        logger.debug('steemd_pager calling Steem.%s(%s, %s, %s)', func.__name__, args, offset, batch_size-1)
        yield func(*args, offset, batch_size-1)

def get_delegation_account_bandwidth(account_name:str=DELEGATION_ACCOUNT, bandwidth_type:str='forum') -> dict:
    return Steem().get_account_bandwidth(account_name, bandwidth_type)

def account_history(account_name:str=DELEGATION_ACCOUNT,
                             include_op_types: Optional[Tuple[str]]=('account_create_with_delegation',),
                             newer_than_block_num: Optional[int]=None,
                             newer_than_datetime: Optional[datetime.datetime]=None,
                             max_items: Optional[int]=None,
                             batch_size:int=10000) -> Iterable[dict]:

    client = Steem(nodes=STEEMD_NODES, no_broadcast=True)

    item_block_num_path = (1, 'block')
    item_timestamp_path = (1, 'timestamp')
    item_op_path = (1, 'op', 0)

    pager = steemd_pager(client.get_account_history, account_name, batch_size=batch_size)
    results = it.chain.from_iterable(pager)
    if newer_than_block_num > 1:
        logger.debug(f'filtering on newer_than_block_num: {newer_than_block_num}')
        results = takewhile(lambda item: get_in(item_block_num_path, item) >= newer_than_block_num, results)
    if newer_than_datetime is not None:
        logger.debug(f'filtering on newer_than_datetime: {newer_than_datetime}')
        results = takewhile(lambda item: datetime.datetime.strptime(get_in(item_timestamp_path, item),'%Y-%m-%dT%H:%M:%S') >= newer_than_datetime, results)
    if include_op_types:
        include_op_types = set(include_op_types)
        logger.debug(f'filtering on include_op_types: {include_op_types}')
        results = filter(lambda item: get_in(item_op_path, item) in include_op_types, results)
    if max_items > 0:
        logger.debug(f'filtering on max_items: {max_items}')
        results = take(max_items, results)
    return (r[1] for r in results)

def get_account_names(*args, **kwargs) -> Iterable[str]:
    account_create_with_delegation_ops = account_history(*args, **kwargs)
    return extract_account_names(account_create_with_delegation_ops)

def extract_account_names(account_create_with_delegation_ops:Iterable[dict]) -> Iterable[str]:
    account_name_path = ('op',1,'new_account_name')
    extractor = partial(get_in, account_name_path)
    return funcy.seqs.imap(extractor, account_create_with_delegation_ops)

def load_accounts(account_names:Iterable[str], client=None) -> Iterable[dict]:
    client = client or Steem()
    chunked_names = chunkify(account_names, 500)
    results = funcy.seqs.imap(client.get_accounts, chunked_names)
    return it.chain.from_iterable(results)

def compute_delegation_ops(
        accounts: Iterable[dict],
        target_delegation_type:Delegation=Delegation.SUB_TO_ZERO,
        min_update: int=MIN_UPDATE,
        inclusive_lower_limit_vests: Amount=INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS,
        min_delegation: Amount=MIN_DELEGATION,
        delegator: str=DELEGATION_ACCOUNT
) -> Generator[ComputedOperation, None, None]:

    # adjust values for target type
    if target_delegation_type is Delegation.SUB_TO_ZERO:
        min_delegation = SPAM_MIN_ACCOUNT_DELEGATION
        inclusive_lower_limit_vests = SPAM_INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS
        min_update = SPAM_MIN_UPDATE


    for acct in accounts:
        delegatee = acct['name']
        acct_vests = Amount(acct['vesting_shares'])
        delegated_vests = Amount(acct['received_vesting_shares'])
        beginning_balance = acct_vests + delegated_vests
        vests_to_delegate = inclusive_lower_limit_vests - beginning_balance

        # cant undelegate amount greater than current delegation
        if vests_to_delegate < 0 and abs(
                float(vests_to_delegate)) > delegated_vests:
            vests_to_delegate = -1.0 * float(delegated_vests)
            vests_to_delegate = Amount('%s VESTS' % vests_to_delegate)

        ending_balance = beginning_balance + vests_to_delegate
        ending_delegated = delegated_vests + vests_to_delegate
        logger.debug(f'Evaluating acct: vests: {acct_vests} delegated_vests:{delegated_vests} beginning_balance:{beginning_balance} vests_to_delegate:{vests_to_delegate} ending_balance:{ending_balance} ending_delegated:{ending_delegated}')
        # skip delegations less than minimum_update
        if abs(float(vests_to_delegate)) < min_update:
            logger.debug('delegation of %s to %s < min_update(%s) -> skipping',vests_to_delegate, delegatee, min_update)
            continue

        delegation_type = Delegation.infer_type(vests_to_delegate,ending_delegated)

        # optionally ignore a certain delegation_type
        if delegation_type != target_delegation_type:
            logger.debug('%s op to %s not in %s -> skipping', delegation_type, delegatee, target_delegation_type)
            continue


        # amount to specify in delegation operation
        op_vesting_shares = delegated_vests + vests_to_delegate

        # skip delegations less than minimum_delegation
        if op_vesting_shares < min_delegation:
            logger.debug('delegation of %s to %s < min_delegation(%s) -> skipping', vests_to_delegate, delegatee, min_delegation)
            continue


        try:
            # sanity checks

            # never delegate more than min
            assert op_vesting_shares <= inclusive_lower_limit_vests

            # no action leaves anyone with less than min
            assert ending_balance >= inclusive_lower_limit_vests

            # no updates less than min_update
            assert abs(
                float(op_vesting_shares - delegated_vests)) >= min_update

            #
            assert op_vesting_shares >= min_delegation

            # confirm correct delegation type
            assert delegation_type == target_delegation_type

            # no action undelegates more than delegation
            if delegation_type in (Delegation.SUB_TO_ZERO, Delegation.SUB_TO_MIN):
                # no negative delegations
                assert delegated_vests > 0

                # undelegation is less than current delegation
                assert abs(float(vests_to_delegate)) <= delegated_vests


        except AssertionError as e:
            logger.exception(
                'error %s, %s', e,
                ComputedOperation(delegator, delegatee, delegation_type, vests_to_delegate,
                                  op_vesting_shares, acct_vests, delegated_vests,
                                  beginning_balance, ending_balance,
                                  ending_delegated))
            continue


        yield ComputedOperation(
                            delegator,
                            delegatee,
                            delegation_type,
                            vests_to_delegate,
                            op_vesting_shares,
                            acct_vests,
                            delegated_vests,
                            beginning_balance,
                            ending_balance,
                            ending_delegated)


def computed_ops_to_steem_ops(computed_ops:Iterable[NamedTuple],) -> Iterable[dict]:
    for op in computed_ops:
        yield operations.DelegateVestingShares(
            delegator=op.delegator,
            vesting_shares=str(op.op_vesting_shares),
            delegatee=op.delegatee).json()


def compute_total_dedelegation_ops(accounts: Iterable[dict]):
    pass


# ----------------------
# Main Program Functions
# ----------------------
def compute_delegation_stats(
        computed_ops: Iterable[ComputedOperation],
        delegation_type:Delegation=None,
        inclusive_lower_limit_sp=INCLUSIVE_LOWER_BALANCE_LIMIT_SP,
        inclusive_lower_limit_vests=INCLUSIVE_LOWER_BALANCE_LIMIT_VESTS,
        min_update=MIN_UPDATE,
        min_delegation=MIN_DELEGATION
) -> dict:
    delegation_stats = {}
    delegation_stats['inclusive_lower_limit_sp'] = inclusive_lower_limit_sp
    delegation_stats['inclusive_lower_limit_vests'] = inclusive_lower_limit_vests
    delegation_stats['min_update'] = min_update
    delegation_stats['min_delegation'] = min_delegation
    delegation_stats['tables'] = []


    computed_ops = list(computed_ops)

    # table 1
    table_data = [
    [ 'Type', 'Count'],
    [
        'NOOP ops',
        len([o for o in computed_ops if o.delegation_type == Delegation.NOOP])
    ],
    [
        'Dedelegate To Zero Ops',
        len([o for o in computed_ops if o.delegation_type == Delegation.SUB_TO_ZERO])
    ],
    [
        'Dedelegate To Min Ops',
        len([op for op in computed_ops if op.delegation_type == Delegation.SUB_TO_MIN])
    ],
    [
        'Delegate To Min Ops',
        len([op for op in computed_ops if
             op.delegation_type == Delegation.ADD_TO_MIN])
    ],
    ]
    title = 'Delegation Op Stats By Type'
    delegation_stats['tables'].append(dict(title=title, table_data=table_data))

    verb = delegation_type.verb

    typed_ops = [o for o in computed_ops]
    logger.debug(f'{len(typed_ops)} typed ops')
    if not typed_ops:
        title = '%s Stats' % verb.title()
        table_data = [
            ['Metric', 'VESTS', 'SP'],
            ['Total To Be %s' % verb, 0,0],
            ['Mean To Be %s' % verb,0,0],
            ['Median To Be %s' % verb, 0,0],
            ['Mode To Be %s' % verb, 0,0],
        ]
        delegation_stats['tables'].append(dict(title=title, table_data=table_data))
        return delegation_stats

    total_vests_to_delegate = sum(
        int(op.vests_to_delegate) for op in typed_ops)
    try:
        mean_vests_to_delegate = statistics.mean(
            int(op.vests_to_delegate) for op in typed_ops)
    except:
        mean_vests_to_delegate = 'n/a'
    median_vests_to_delegate = statistics.median(
        int(op.vests_to_delegate) for op in typed_ops)
    try:
        mode_vests_to_delegate = statistics.mode(
            int(op.vests_to_delegate) for op in typed_ops)
    except Exception as e:
        mode_vests_to_delegate = 'n/a'


    # table 2
    title = '%s Stats' % delegation_type.verb
    table_data = [
        ['Metric', 'VESTS', 'SP'],
        ['total to be %s' % verb, total_vests_to_delegate],
        ['mean to be %s' % verb, mean_vests_to_delegate],
        ['median to be %s' % verb, median_vests_to_delegate],
        ['mode to be %s' % verb, mode_vests_to_delegate],
    ]

    for row in table_data[1:]:
        row.append(converter.vests_to_sp(row[1]))
    delegation_stats['tables'].append(dict(title=title, table_data=table_data))


    # before/after stats
    mean_acct_balance_before = statistics.mean(
        int(op.beginning_balance) for op in computed_ops)
    median_acct_balance_before = statistics.median(
        int(op.beginning_balance) for op in computed_ops)

    mean_acct_balance_after = statistics.mean(
        int(op.ending_balance) for op in computed_ops)
    median_acct_balance_after = statistics.median(
        int(op.ending_balance) for op in computed_ops)

    mean_delegated_before = statistics.mean(
        int(op.delegated_vests) for op in computed_ops)

    median_delegated_before = statistics.median(
        int(op.delegated_vests) for op in computed_ops)

    mean_delegated_after = statistics.mean(
        int(op.ending_delegated) for op in computed_ops)

    median_delegated_after = statistics.median(
        int(op.ending_delegated) for op in computed_ops)

    min_delegated_before = min(int(op.delegated_vests) for op in computed_ops)
    min_delegated_after = min(int(op.ending_delegated) for op in computed_ops)

    count_zero_delegated_before = len(
        [op for op in computed_ops if op.delegated_vests == 0])
    count_zero_delegated_after = len(
        [op for op in computed_ops if op.ending_delegated == 0])

    # table 3
    title = 'Before/After Acct Stats'
    table_data = [['Metric', 'Before', 'After'], [
        'min acct balance',
        min(int(op.beginning_balance) for op in computed_ops),
        min(int(op.ending_balance) for op in computed_ops)
    ], [
        'mean acct balance', mean_acct_balance_before, mean_acct_balance_after
    ], [
        'median acct balance', median_acct_balance_before,
        median_acct_balance_after
    ], [
        'count accts w/min balance',
        len([
            op for op in computed_ops
            if op.beginning_balance == inclusive_lower_limit_vests
        ]),
        len([
            op for op in computed_ops
            if op.ending_balance == inclusive_lower_limit_vests
        ])
    ], ['min delegated', min_delegated_before, min_delegated_after], [
        'mean delegated', mean_delegated_before, mean_delegated_after
    ], ['median delegated', median_delegated_before, median_delegated_after], [
        'count accts w/zero delegation', count_zero_delegated_before,
        count_zero_delegated_after
    ]]

    delegation_stats['tables'].append(dict(title=title, table_data=table_data))
    return delegation_stats

# step 4
def show_delegation_stats(delegation_stats: dict) -> None:
    for table in delegation_stats['tables']:
        print_table(**table)

def save_delegation_stats(delegation_stats: dict, run_datetime:datetime) -> None:
    filename = BASE_DELEGATION_STATS_FILENAME % run_datetime.isoformat()
    with open(filename) as f:
        json.dump(delegation_stats, f)

# step 5
def build_delegation_tx(op_group: List[dict],
         steemd_instance:Steem,
          delegation_account: str=DELEGATION_ACCOUNT,
          expiration:int = 60) -> dict:
    tx = TransactionBuilder(steemd_instance=steemd_instance, no_broadcast=True)
    tx.appendOps([operations.DelegateVestingShares(**op) for op in op_group])
    tx.appendSigner(DELEGATION_ACCOUNT, 'active')
    return tx

def sign_tx(unsigned_tx: dict) -> dict:
    unsigned_tx.sign()
    return unsigned_tx

def broadcast_tx(signed_tx: dict,steemd_instance: Steem):
    tx = TransactionBuilder(tx=signed_tx, steemd_instance=steemd_instance, no_broadcast=False)
    return tx.broadcast()


# step 6
def process_ops(grouped_ops: Iterable[List[dict]],
                key: Optional[str]=None,
                no_broadcast: bool=True,
                expiration: int=TRANSACTION_EXPIRATION,
                delegation_account: str=DELEGATION_ACCOUNT,
                filenames=('processed.json', 'unprocessed.json'),
                bandwidth_limit:int=0):
    processed_file, unprocessed_file = filenames

    init_results_files(filenames)


    steemd = Steem(
        nodes=STEEMD_NODES,
        no_broadcast=no_broadcast,
        keys=[key],
        debug=True)


    broadcaster = Steem(nodes=STEEMD_NODES, debug=True)

    for op_group in grouped_ops:
        #logger.info(f'bytes (bandwidth) broadcasted:{processed_bytes} unbroadcasted:{unprocessed_bytes}')
        try:
            error_encountered = False
            unsigned_tx = build_delegation_tx(op_group, steemd_instance=steemd)
            unsigned_len = len(json.dumps(unsigned_tx).encode())

            #unprocessed_bytes += unsigned_len

            #logger.debug(f'unsigned tx:{unsigned_tx.json()}')
            signed_tx = None
            if key:
                signed_tx = sign_tx(unsigned_tx)
                signed_len = len(json.dumps(signed_tx).encode())

            #processed_bytes += signed_len
            #logger.debug(f'signed tx:{signed_tx.json()}')
            if signed_tx and not no_broadcast:
                broadcast_tx(signed_tx=signed_tx, steemd_instance=broadcaster)
        except KeyboardInterrupt:
            error_encountered = True
            raise KeyboardInterrupt
        except Exception as e:
            logger.exception('Error while broadcasting')
            error_encountered = True
        finally:
            if error_encountered:
                atomic_append_json(unprocessed_file, op_group)
                logger.info('appending ops to %s', unprocessed_file)
            else:
                atomic_append_json(processed_file, op_group)
                logger.info('appending unrecorded ops to %s', processed_file)




def main(args):
    key = args.wif
    account_names = args.account_names
    ops = args.ops
    show_stats = args.stats
    no_broadcast = args.no_broadcast
    newer_than_datetime = args.newer_than_datetime
    newer_than_block_num = args.newer_than_block_num
    max_items = args.max_items
    delegation_type = args.delegation_type
    run_datetime = args.run_datetime

    if not ops:

        if delegation_type == Delegation.SUB_TO_ZERO and not account_names:
            raise ValueError('--account_names required for delegation to zero')

        account_names_to_process = args.account_names or get_account_names(newer_than_block_num=newer_than_block_num,
                                                                           newer_than_datetime=newer_than_datetime,
                                                                           max_items=max_items)
        accounts = load_accounts(account_names_to_process)

        computed_ops = compute_delegation_ops(accounts, target_delegation_type=delegation_type)

        stats_ops, computed_ops = it.tee(computed_ops, 2)
        logger.info('computing %s ops...' % delegation_type)

        delegation_stats = compute_delegation_stats(stats_ops,
                                                    delegation_type=delegation_type)

        if show_stats:
            show_delegation_stats(delegation_stats)
        save_delegation_stats(delegation_stats)


        ops = computed_ops_to_steem_ops(computed_ops)

    grouped_ops = group_ops(ops)
    if not args.yes:
        proceed = input('Proceed with operation? y/n:')
        if proceed != 'y':
            return
    process_ops(
        grouped_ops=grouped_ops,
        key=key,
        no_broadcast=no_broadcast)

def to_zero(args):
    key = args.wif
    account_names_to_process = args.account_names
    ops = args.ops
    show_stats = args.stats
    no_broadcast = args.no_broadcast
    newer_than_datetime = args.newer_than_datetime
    newer_than_block_num = args.newer_than_block_num
    max_items = args.max_items

    delegation_type = args.delegation_type

    if not ops:
        if not isinstance(account_names_to_process,list) or not account_names_to_process:
            raise ValueError('--account_names is a required option for delegation to zero')

        logger.info('getting accounts from steemd, be patient...')
        account_names_to_process = args.account_names or get_account_names()
        accounts = load_accounts(account_names_to_process)

        logger.info('computing %s ops...' % delegation_type)
        computed_ops = compute_delegation_ops(accounts,
                                              target_delegation_type=delegation_type)

        stats_ops, computed_ops = it.tee(computed_ops, 2)
        logger.info('computing aggregate stats...')
        delegation_stats = compute_delegation_stats(stats_ops,
                                                    delegation_type=delegation_type)

        logger.info('delegation stats')
        show_delegation_stats(delegation_stats)

        ops = computed_ops_to_steem_ops(computed_ops)

    grouped_ops = group_ops(ops)

    process_ops(
        grouped_ops=grouped_ops,
        key=key,
        no_broadcast=no_broadcast)

def add_to_min(args):
    key = args.wif
    account_names = args.account_names
    ops = args.ops
    show_stats = args.stats
    no_broadcast = args.no_broadcast
    newer_than_datetime = args.newer_than_datetime
    newer_than_block_num = args.newer_than_block_num
    max_items = args.max_items

    delegation_type = args.delegation_type


    if not ops:
        logger.debug('getting accounts from steemd, be patient...')
        account_names_to_process = args.account_names or get_account_names(newer_than_block_num=newer_than_block_num,
                                                                           newer_than_datetime=newer_than_datetime,
                                                                           max_items=max_items)
        accounts = load_accounts(account_names_to_process)

        logger.info('computing %s ops...' % delegation_type)
        computed_ops = compute_delegation_ops(accounts, target_delegation_type=delegation_type)

        ops = computed_ops_to_steem_ops(computed_ops)
        if not ops:
            logger.info('No ops to sign or brodcast.')
            return

        logger.info('computing aggregate stats...')
        delegation_stats = compute_delegation_stats(computed_ops,delegation_type=delegation_type)

        logger.info('delegation stats')
        show_delegation_stats(delegation_stats)


    grouped_ops = group_ops(ops)

    process_ops(
        grouped_ops=grouped_ops,
        key=key,
        no_broadcast=no_broadcast)

def sub_to_min(args):
    key = args.wif
    ops = args.ops
    no_broadcast = args.no_broadcast
    newer_than_datetime = args.newer_than_datetime
    newer_than_block_num = args.newer_than_block_num
    max_items = args.max_items

    delegation_type = args.delegation_type


    if not ops:
        logger.info('getting accounts from steemd, be patient...')
        account_names_to_process = args.account_names or get_account_names(newer_than_block_num=newer_than_block_num,
                                                                           newer_than_datetime=newer_than_datetime,
                                                                           max_items=max_items)
        accounts = load_accounts(account_names_to_process)

        logger.info('computing %s ops...' % delegation_type)
        computed_ops = compute_delegation_ops(accounts, target_delegation_type=delegation_type)

        stats_ops, computed_ops = it.tee(computed_ops, 2)
        logger.info('computing aggregate stats...')
        delegation_stats = compute_delegation_stats(stats_ops,
                                                    delegation_type=delegation_type)

        logger.info('delegation stats')
        show_delegation_stats(delegation_stats)

        ops = computed_ops_to_steem_ops(computed_ops)

    grouped_ops = group_ops(ops)
    if not args.yes:
        proceed = input('Proceed with operation? y/n:')
        if proceed != 'y':
            return
    process_ops(
        grouped_ops=grouped_ops,
        key=key,
        no_broadcast=no_broadcast)

def to_min(args):
    key = args.wif
    account_names = args.account_names
    ops = args.ops
    show_stats = args.stats
    no_broadcast = args.no_broadcast
    newer_than_datetime = args.newer_than_datetime
    newer_than_block_num = args.newer_than_block_num
    max_items = args.max_items
    signing_start = args.signing_start
    delegation_type = args.delegation_type

if __name__ == '__main__':
    parser = argparse.ArgumentParser('Steemit [un]delegation script')
    parser.add_argument('--wif', type=readlines_and_strip_text_type)
    parser.add_argument('--account_names', type=readlines_and_strip_text_type)
    parser.add_argument('--ops', type=read_json_type)
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--no_broadcast', action='store_true')
    parser.add_argument('--newer_than_datetime',type=utc_datetime, help='ISO Datetime, eg, 1970-01-01T00:00.00Z')
    parser.add_argument('--newer_than_block_num', type=int, default=1)
    parser.add_argument('--max_items', type=int, default=0)
    parser.add_argument('--yes', action='store_true' )
    parser.set_defaults(run_datetime=datetime.datetime.utcnow())
    subparsers = parser.add_subparsers()

    parser_to_zero = subparsers.add_parser('to-zero')
    parser_to_zero.set_defaults(func=to_zero, delegation_type=Delegation.SUB_TO_ZERO)


    parser_add_to_min = subparsers.add_parser('delegate-to-min')
    parser_add_to_min.set_defaults(func=add_to_min, delegation_type=Delegation.ADD_TO_MIN)

    parser_sub_to_min = subparsers.add_parser('dedelegate-to-min')
    parser_sub_to_min.set_defaults(func=sub_to_min, delegation_type=Delegation.SUB_TO_MIN)

    parser_to_min = subparsers.add_parser('either-to-min')
    parser_to_min.set_defaults(func=to_min, delegation_type=Delegation.TO_MIN)

    args = parser.parse_args()

    logger.debug(f'args:{args}')
    args.func(args)


