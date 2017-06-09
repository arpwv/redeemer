#!/usr/bin/env python3
# coding=utf-8

import sys
import json

from steem import Steem
from steem.transactionbuilder import TransactionBuilder
from steembase import operations

OPS_PER_TRANSACTION = 100

ops_file = sys.argv[1]
wif_file = sys.argv[2]

with open(ops_file) as f:
    ops = json.load(f)

with open(wif_file) as f:
    key = f.read().strip()

def chunkify(iterable, chunksize=OPS_PER_TRANSACTION ):
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

s = Steem(no_broadcast=True, keys=[key])

for i,chunk in enumerate(chunkify(ops)):
    tx = TransactionBuilder(no_broadcast=True)
    while True:
        try:
            tx.appendOps([operations.DelegateVestingShares(**json.loads(op)) for op in chunk])
            tx.appendSigner('steem','active')
            tx.sign()
            print(json.dumps(tx))
            print('broadcasted tx #%s' % i, file=sys.stderr)
            break
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except Exception as e:
            print(e, file=sys.stderr)
