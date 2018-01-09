
from decimal import Decimal
from collections import defaultdict


class Stats:
    def __init__(self, mode_factor=1000):
        self.mode_factor = Decimal(mode_factor)
        self.reset()

    def reset(self):
        self.total_redeemed_vests = Decimal(0)
        self.total_accounts_handled = Decimal(0)
        self.mean_redeemed_vests = Decimal(0)
        self.mode_redeemed_vests = 0
        self.single_largest_redeemed_vests = ('', Decimal(0))
        self._mode = defaultdict(int)

    def add(self, account_name, delta):
        delta = abs(Decimal(delta))
        if delta > self.single_largest_redeemed_vests[1]:
            self.single_largest_redeemed_vests = (account_name, delta)
        self.total_accounts_handled += Decimal(1)
        self.total_redeemed_vests += delta
        self.mean_redeemed_vests = self.total_redeemed_vests / self.total_accounts_handled
        qv = self.quantized_vests(delta)
        if qv > 0:
            self._mode[qv] += 1
            if self._mode[qv] > self._mode[self.mode_redeemed_vests]:
                self.mode_redeemed_vests = qv

    def quantized_vests(self, vests):
        # remove the decimal and round to the nearest 1000 VESTS
        return (vests / self.mode_factor).to_integral() * self.mode_factor

    def get(self):
        return {
            "total_redeemed_vests": self.total_redeemed_vests,
            "total_accounts_handled": self.total_accounts_handled,
            "mean_redeemed_vests": self.mean_redeemed_vests,
            "mode_redeemed_vests": Decimal(self.mode_redeemed_vests),
            "single_largest_redeemed_vests": {
                "account": self.single_largest_redeemed_vests[0],
                "amount": self.single_largest_redeemed_vests[1],
            }
        }
