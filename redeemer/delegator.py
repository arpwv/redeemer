import logging
from decimal import Decimal

from steem import Steem
from steem.steemd import Steemd
from steem.instance import set_shared_steemd_instance
from steem.converter import Converter
from steembase import operations
from steem.transactionbuilder import TransactionBuilder


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

        self.limit = limit
        self.logger = logger
        self.STEEM_PER_VEST = Decimal(
            Converter(
                self.steem).steem_per_mvests() /
            1e6)  # TODO: check Converter. float math?
        self.TARGET_VESTS = self.TARGET_SP / self.STEEM_PER_VEST
        # TODO: chain_props['account_creation_fee'] / self.STEEM_PER_VEST
        self.MIN_VESTS_DELTA = Decimal(204.84)
        self.MIN_VESTS = self.MIN_VESTS_DELTA * 10

    def get_delegated_accounts(self, account, last_idx=''):
        results = self.steem.get_vesting_delegations(
            account, last_idx, self.limit)
        if not results or (last_idx is None and len(results) == 0) or (last_idx is not None and len(results) == 1):
            return ([], None)  # end of the line
        if last_idx:
            results.pop(0)  # if offset specified, shift result

        delegations = {r['delegatee']: r['vesting_shares'] for r in results}
        accounts = self.steem.get_accounts(list(delegations.keys()))
        if accounts is None:
            return ([], None)  # end of the line, again
        for account in accounts:
            account['vesting_shares_from_delegator'] = delegations[account['name']]

        return (accounts, results[-1]['delegatee'])

    def vests_to_delegate(self, acct):
        name = acct['name']
        account_vests = Decimal(acct['vesting_shares'].split(' ')[0])
        old_delegated_vests = Decimal(
            acct['vesting_shares_from_delegator'].split(' ')[0])

        if name in self.deplorables:
            new_delegated_vests = 0
        else:
            new_delegated_vests = max(0, self.TARGET_VESTS - account_vests)

        # do not process attempted increases in delegation
        if new_delegated_vests > old_delegated_vests:
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

    def get_delegation_deltas(self, delegator_account_name, accounts):
        deltas = [self.vests_to_delegate(account) for account in accounts]
        return [item for item in deltas if item]

    def delegate(
            self,
            delegator_account_name,
            last_idx,
            expiration=60,
            dry_run=True,
            wifs=[]):
        accounts, last_idx = self.get_delegated_accounts(
            delegator_account_name, last_idx=last_idx)
        if not accounts:
            return ([], last_idx)

        deltas = self.get_delegation_deltas(delegator_account_name, accounts)
        delegation_ops = []
        for delta in deltas:
            delegation_ops.append(operations.DelegateVestingShares(
                delegator=delegator_account_name,
                vesting_shares=delta['new_vests'],
                delegatee=delta['name']
            ))
        if len(delegation_ops) == 0:
            self.logger.info('no operations in this group to broadcast.')
            return ([], last_idx)

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
