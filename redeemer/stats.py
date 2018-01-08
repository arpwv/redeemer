
from decimal import Decimal
from collections import defaultdict

class Stats:
  def __init__(self, mode_factor=1000):
    self.total_redeemed_vests = 0
    self.total_accounts_handled = 0
    self.mean_redeemed_vests = 0
    self.mode_redeemed_vests = 0
    self.single_largest_redeemed_vests = ('', Amount('0 VESTS'))
    self._mode = defaultdict(int)
    self.mode_factor = Decimal(mode_factor)

  def add(self, old_vesting_amount, new_vesting_amount):
    delta = new_vesting_amount - old_vesting_amount
    if delta > self.single_largest_redeemed_vests[1]:
      self.single_largest_redeemed_vests = (account_name, delta)
    self.total_accounts_handled += 1
    self.total_redeemed_vests += delta
    self.mean_redeemed_vests = self.total_redeemed_vests / self.total_accounts_handled
    qv = self.quantized_vests(delta)
    self._mode[qv] += 1
    if self._mode[qv] > self._mode[self.mode_redeemed_vests]:
      self.mode_redeemed_vests = qv

  def quantized_vests(self, vests):
    # remove the decimal and round to the nearest 1000 VESTS
    vests = Decimal(str(vests).split(' VESTS')[0])
    return int((vests / self.mode_factor).to_integral() * self.mode_factor) 
