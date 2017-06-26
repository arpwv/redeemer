#!/usr/bin/env python3
# coding=utf-8

import sys
import json
import argparse

from steem import Steem
from steem.transactionbuilder import TransactionBuilder
from steembase import operations

STEEMIT_MAX_BLOCK_SIZE = 65536 # "maximum_block_size": 65536
MAX_OPS_GROUP_SIZE = int(STEEMIT_MAX_BLOCK_SIZE / 2)


def group_ops(ops, max_size=MAX_OPS_GROUP_SIZE, max_len=500):
    group_size = 0
    group = []
    for op in ops:
        op_size = op_size = len(json.dumps(operations.DelegateVestingShares(**op).json()))
        if group_size + op_size > max_size or len(group) == max_len:
            yield group
            group = [op]
            group_size = op_size
        else:
            group.append(op)
            group_size += op_size
    yield group



if __name__ == '__main__':
    parser = argparse.ArgumentParser('Delegation Op Signer')
    parser.add_argument('ops_file', type=str)
    parser.add_argument('wif_file', type=str)
    parser.add_argument('--start_index', type=int, default=0)
    args = parser.parse_args()

    with open(args.ops_file) as f:
        ops = json.load(f)
        ops = ops[args.start_index:]

    with open(args.wif_file) as f:
        key = f.read().strip()

    s = Steem(keys=[key])

    for group_num, op_group in enumerate(group_ops(ops)):
        error_count = 0
        start_op_index = ops.index(op_group[0]) + args.start_index
        end_op_index = ops.index(op_group[-1]) + args.start_index
        while True:
            group_size = len(json.dumps(op_group))
            group_len = len(op_group)

            try:
                
                tx = TransactionBuilder()
                tx.appendOps([operations.DelegateVestingShares(**op) for op in op_group])
                tx.appendSigner('steem', 'active')
                tx.sign()
                tx.broadcast()
                print(json.dumps(tx))
                break
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except Exception as e:
                error_count += 1
                print(e, file=sys.stderr)
                
                if error_count == 3:
                    with open('error_%s_ops_start_%s_end%s.json' % (group_num, start_op_index, end_op_index), 'w') as f:
                        json.dump(op_group, f)
                    with open('error_%s.txt' % group_num,'w') as f:
                        f.write('%s' % e.__repr__())
                    break
            else:
                print('broadcasted group:%s start:%s end:%s len:%s size:%s' % (
                    group_num, start_op_index, end_op_index, group_len,
                    group_size),
                      file=sys.stderr)
# vim: set number tabstop=4 shiftwidth=4 expandtab:
