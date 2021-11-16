#!/bin/env python3


import sys

from datetime import datetime

trades_file = sys.argv[1]

fees = 0.001


profits = []
with open(trades_file, 'rt') as trades:
    for line in trades:
        # entry_ts, price_entry, exit_ts, price_exit, quantity, est_pct = map(float, line.strip().split(','))
        entry_ts, price_entry, exit_ts, price_exit, quantity, est_pct = line.strip().split(',')
        try:
            entry_time = datetime.fromtimestamp(float(entry_ts)/1000)
        except ValueError:
            entry_time = ''
        entry_amnt = float(price_entry) * float(quantity)
        exit_amnt = float(price_exit) * float(quantity)
        pnl = entry_amnt - exit_amnt - (exit_amnt * fees) - (entry_amnt * fees)
        profits.append(pnl)
        print('%(date)s PNL: %(pnl).4f' % {
            'date': entry_time, 'pnl': pnl})

print('%(n_trades)i Total P&L %(tot_pnl).4f' % {
    'n_trades': len(profits),'tot_pnl': sum(profits)})
