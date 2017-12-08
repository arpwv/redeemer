# coding=utf-8
import steem
import steem.converter
from steem.amount import Amount
steemd = steem.Steem(keys=[],no_broadcast=True)
converter = steem.converter.Converter()

def get_batch(start_dt):
    last_dt = start_dt
    all_results = []
    while True:
        results = steemd.get_expiring_vesting_delegations("steem", last_dt, 999)
        all_results.extend(results)
        print(f'results:{len(results)} all_results:{len(all_results)})')
        if len(all_results) >=  64935:
            break
        if len(results) == 999:
            last_dt = results[-1]['expiration']
        else:
            break
    return all_results
r = get_batch('2017-10-15T00:00')

def get_total(results):
    amounts = (Amount(item['vesting_shares']) for item in results)
    total = Amount('0 VESTS')
    for amount in amounts:
        total += amount
    return total
