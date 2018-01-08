import logging
from decimal import Decimal

from steem import Steem
from steem.steemd import Steemd
from steem.instance import set_shared_steemd_instance
from steem.converter import Converter
from steembase import operations
from steem.transactionbuilder import TransactionBuilder

class Delegator(object):

  MIN_ACCOUNT_SP = 15

  def __init__(self, steem=None, limit=1000, logger=logging.NullHandler):
      if steem is None:
        dry_run = True
        self.steem = Steem(nodes=['https://api.steemit.com'])
      else:
        self.steem = steem

      self.limit = limit
      self.logger = logger
      self.STEEM_PER_VEST = Decimal(Converter(self.steem).steem_per_mvests() / 1e6)
      self.MIN_ACCOUNT_VESTS = self.MIN_ACCOUNT_SP / self.STEEM_PER_VEST
      self.MIN_VESTS_DELTA = 204.84 # TODO: account_creation_fee / steem_per_vest

  def get_delegated_accounts(self, account, last_idx=''):
      results = self.steem.get_vesting_delegations(account, last_idx, self.limit)
      if last_idx:
          results.pop(0) # if offset specified, shift result
      delegations = {r['delegatee']: r['vesting_shares'] for r in results}

      accounts = self.steem.get_accounts(list(delegations.keys()))
      for account in accounts:
        account['vesting_shares_from_delegator'] = delegations[account['name']]

      return (accounts, results[-1]['delegatee'])

  def vests_to_delegate(self, acct):
      name = acct['name']
      account_vests = Decimal(acct['vesting_shares'].split(' ')[0])
      old_delegated_vests = Decimal(acct['vesting_shares_from_delegator'].split(' ')[0])
      new_delegated_vests = max(0, self.MIN_ACCOUNT_VESTS - account_vests)

      delta = new_delegated_vests - old_delegated_vests

      if abs(delta) < self.MIN_VESTS_DELTA:
          return None # blockchain-enforced minimum delta

      if delta > 0:
          return None # do not increase steemit delegation

      print("% -17s from % 7.2f to % 7.2f -- % 7.2f" % (
          name,
          old_delegated_vests * self.STEEM_PER_VEST,
          new_delegated_vests * self.STEEM_PER_VEST,
          delta * self.STEEM_PER_VEST))

      return "%.6f VESTS" % new_delegated_vests

  def get_delegation_op(self, delegator_account_name, account):
      new_delegated_vests = self.vests_to_delegate(account)

      if new_delegated_vests is None:
          return None # no change

      return operations.DelegateVestingShares(
          delegator=delegator_account_name,
          vesting_shares=new_delegated_vests,
          delegatee=account['name']
      )    
 
  def delegate(self, delegator_account_name, last_idx, expiration=60, dry_run=True, wifs=[]):
    accounts, last_idx = self.get_delegated_accounts(delegator_account_name, last_idx=last_idx)
    if len(accounts) == 0:
      return ([], last_idx)
    delegation_ops = [ self.get_delegation_op(delegator_account_name, account) for account in accounts ]
    tx = TransactionBuilder(steemd_instance=self.steem, expiration=expiration)
    tx.appendOps([op for op in delegation_ops if op])
    [ tx.appendWif(wif) for wif in wifs ]
    if len(wifs) is not 0:
      tx.sign()
    if not dry_run:
      result = tx.broadcast()
      self.logger.info('transaction broadcast. result: %s', result)
    return (
      [(account, self.vests_to_delegate(account)) for account in accounts ],
      last_idx
    )

