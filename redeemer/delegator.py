import logging
from decimal import Decimal
from datetime import datetime

from steem import Steem
from steembase import operations
from steem.transactionbuilder import TransactionBuilder

def amount(steem_amount):
    # in: `3.000 STEEM`, out: Decimal('3.000')
    return Decimal(steem_amount.split(' ')[0])

def days_since(date):
    interval = datetime.today() - datetime.strptime(date, '%Y-%m-%dT%H:%M:%S')
    return interval.days

class Delegator(object):

    TARGET_SP = 15

    def __init__(
            self,
            steem=None,
            limit=1000,
            logger=logging.NullHandler,
            deplorables=None):
        if steem is None:
            dry_run = True
            self.steem = Steem(nodes=['https://api.steemit.com'])
        else:
            self.steem = steem

        if deplorables is not None:
            self.deplorables = deplorables
        else:
            self.deplorables = set()

        # info for steem/vest ratio
        global_props = self.steem.get_dynamic_global_properties()
        vesting_steem = amount(global_props['total_vesting_fund_steem'])
        vesting_shares = amount(global_props['total_vesting_shares'])

        # load dynamic acct creation fee
        chain_props = self.steem.get_chain_properties()
        account_creation_fee = amount(chain_props['account_creation_fee'])

        self.limit = limit
        self.logger = logger
        self.STEEM_PER_VEST = vesting_steem / vesting_shares
        self.TARGET_VESTS = self.TARGET_SP / self.STEEM_PER_VEST
        self.MIN_VESTS_DELTA = account_creation_fee / self.STEEM_PER_VEST
        self.MIN_VESTS = self.MIN_VESTS_DELTA * 10

    def get_delegated_accounts(self, account, last_idx=''):
        results = self.steem.get_vesting_delegations(
            account, last_idx, self.limit)

        if last_idx and results and results[0]['delegatee'] == last_idx:
            # if offset specified, we received results, and first result is the
            #   previous request's last result, shift result.
            results.pop(0)

        if not results:
            return ([], None)  # end of the line

        delegations = {r['delegatee']: r['vesting_shares'] for r in results}
        accounts = self.steem.get_accounts(list(delegations.keys()))
        for acct in accounts:
            acct['vesting_shares_from_delegator'] = delegations[acct['name']]

        return (accounts, results[-1]['delegatee'])

    def vests_to_delegate(self, acct):
        name = acct['name']
        account_vests = amount(acct['vesting_shares'])
        old_delegated_vests = amount(acct['vesting_shares_from_delegator'])

        if name in self.deplorables:
            new_delegated_vests = 0
        elif account_vests == 0:
            new_delegated_vests = self.MIN_VESTS
        elif days_since(acct['last_bandwidth_update']) > 90:
            _inactive_target = self.TARGET_VESTS / 3 - account_vests
            new_delegated_vests = max(self.MIN_VESTS, _inactive_target)
        else:
            new_delegated_vests = max(0, self.TARGET_VESTS - account_vests)

        has_powered_down = (amount(acct['vesting_withdraw_rate']) > 0.000001
                            or int(acct['withdrawn']) > 0
                            or int(acct['to_withdraw']) > 0)

        # do not process attempted increases in delegation
        if has_powered_down and new_delegated_vests > old_delegated_vests:
            return None

        # if target vests are below minimum vests, round up.
        if new_delegated_vests > 0 and new_delegated_vests < self.MIN_VESTS:
            new_delegated_vests = self.MIN_VESTS

        # theoretically an account could have a delegation below the min delta;
        #   to reset it, we must /raise/ it above the bar first.
        elif new_delegated_vests == 0 and old_delegated_vests < self.MIN_VESTS_DELTA:
            new_delegated_vests = max(
                self.MIN_VESTS,
                old_delegated_vests +
                self.MIN_VESTS_DELTA)

        delta = new_delegated_vests - old_delegated_vests
        if abs(delta) < self.MIN_VESTS_DELTA:
            return None  # blockchain-enforced minimum delta

        return {'name': name,
                'shares': acct['vesting_shares'],
                'delta_vests': delta,
                'new_vests': "%.6f VESTS" % new_delegated_vests,
                'old_vests': acct['vesting_shares_from_delegator']}

    def get_delegation_deltas(self, accounts):
        deltas = [self.vests_to_delegate(account) for account in accounts]
        return [item for item in deltas if item]

    def delegate(
            self,
            delegator,
            last_idx,
            expiration=60,
            dry_run=True,
            wifs=[]):
        accounts, last_idx = self.get_delegated_accounts(delegator, last_idx)
        if not accounts:
            return ([], last_idx)

        deltas = self.get_delegation_deltas(accounts)
        if not deltas:
            return ([], last_idx)

        delegation_ops = []
        for delta in deltas:
            delegation_ops.append(operations.DelegateVestingShares(
                delegator=delegator,
                vesting_shares=delta['new_vests'],
                delegatee=delta['name']
            ))

        tx = TransactionBuilder(
            steemd_instance=self.steem,
            expiration=expiration)
        tx.appendOps(delegation_ops)
        [tx.appendWif(wif) for wif in wifs]
        if len(wifs):
            tx.sign()

        if not dry_run:
            result = tx.broadcast()
            self.logger.info('transaction broadcast. result: %s', result)

        return (deltas, last_idx)
