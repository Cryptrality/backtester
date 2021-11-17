import json
import talib
import numpy
from datetime import datetime
from cryptrality.misc.utils import str_to_minutes
import argparse
import os
import pprint

parser = argparse.ArgumentParser(description='MACD short scalping')
parser.add_argument('-a', '--asset', dest='asset', default='BTC',
                    help='Base Asset, default BTC')

parser.add_argument('--start', dest='start_date', type=str,
                    help='Start date of the backtest, Time sting int the format d-m-yy, eg "1-9-21"', required = True)
parser.add_argument('--end', dest='end_date', type=str,
                    help='End date of the backtest, Time sting int the format d-m-yy, eg "30-9-21"', required = True)
parser.add_argument('--out', dest='trade_out', type=str, default='strategy_trades.csv',
                    help=('File name to store trades informations, in csv format. Default '
                        '"strategy_trades.csv" in the current directory'))

args = parser.parse_args()


os.environ['DATE_START'] = args.start_date
os.environ['DATE_END'] = args.end_date
from cryptrality.core import *
from cryptrality.exchanges.backtest_binance_spot import *


BUY_AMOUNT = 100

QUOTED_ASSET = "USDT"
BASE_ASSET = args.asset

TRADE_SYMBOL = "%s%s" % (BASE_ASSET, QUOTED_ASSET)

CANDLE_PERIOD_STR = "15m"

CANDLE_PERIOD_MINUTES = str_to_minutes(CANDLE_PERIOD_STR)

EMA_PERIOD = 40
EMA_PERIOD2 = 10
CSV_OUT = args.trade_out


## Caching info from previous candle/stats



in_position = False

min_notional = 10.1

lastprice = last_price(TRADE_SYMBOL)

quoted_asset_balance = get_balance_quoted_asset(QUOTED_ASSET)
quoted_asset_free = float(quoted_asset_balance['free'])
quoted_asset_locked = float(quoted_asset_balance['locked'])


try:
    STEP_SIZE = get_step_size(TRADE_SYMBOL)
except NameError:
    print('WARNING: set an arbitrary step size')
    STEP_SIZE = 0.00001


quantity = 0
position_open_rec = None
entry_time = None

historical_data = get_historical_klines(
   TRADE_SYMBOL, CANDLE_PERIOD_MINUTES, CANDLE_PERIOD_STR, 300)

ema_long_values=[None]
ema_short_values=[None]

def update_ochl(historical_data, candle, max_len=100):
    historical_data['open'].append(float(candle['o']))
    historical_data['close'].append(float(candle['c']))
    historical_data['high'].append(float(candle['h']))
    historical_data['low'].append(float(candle['l']))
    historical_data['open'] = historical_data['open'][-max_len:]
    historical_data['close'] = historical_data['close'][-max_len:]
    historical_data['high'] = historical_data['high'][-max_len:]
    historical_data['low'] = historical_data['low'][-max_len:]
    return historical_data



@schedule(interval="15m", symbol="BTCUSDT", window_size=200)
def on_message(ws, message):
    global historical_data, ema_long_values, ema_short_values, in_position, quantity, position_open_rec, entry_time

    #print('received message')
    json_message = json.loads(message)

    if json_message['e'] == 'kline':
        candle = json_message['k']
    else:
        # check order update status
        if json_message['e'] == 'ORDER_TRADE_UPDATE':
            pass
        pprint.pprint(json_message)
        return

    is_candle_closed = candle['x'] and candle['i'] == CANDLE_PERIOD_STR
    close = float(candle['c'])

    if is_candle_closed and candle['i'] == CANDLE_PERIOD_STR:
        candle_time = datetime.fromtimestamp(int(candle['t']) / 1000)
        print("%s candle closed at %s" % (candle_time, close))
        historical_data = update_ochl(historical_data, candle, 2*EMA_PERIOD)
        np_closes = numpy.array(historical_data['close'], dtype=float)
        ema_values_long = talib.EMA(np_closes, EMA_PERIOD)
        ema_values_short = talib.EMA(np_closes, EMA_PERIOD2)

    if is_candle_closed and in_position and candle['i'] == CANDLE_PERIOD_STR:
        if position_open_rec is None:
            position_amount, position_open_rec = get_position(
                TRADE_SYMBOL, 'LONG')
        if ema_values_long[-1] and ema_values_long[-1] > ema_values_short[-1]:
            position_amount = position_open_rec['positionAmt']
            filled_quantity, avg_price = order_market(TRADE_SYMBOL, position_amount, "SELL")
            entry_price = float(position_open_rec['entryPrice'])
            current_price = historical_data['close'][-1]
            with open(CSV_OUT, 'at') as trade_records:
                record = '%s,%s,%s,%s,%s,%.4f\n' % (
                    entry_time, entry_price,
                    candle['t'], current_price, filled_quantity,
                    (entry_price - current_price) / entry_price * 100)
                trade_records.write(record)
            in_position = False
            position_open_rec = None
            entry_time = None

    elif is_candle_closed and candle['i'] == CANDLE_PERIOD_STR and not in_position:
        buy = False
        if ema_values_long[-1] and ema_values_long[-1] < ema_values_short[-1]:
            buy = True
            quantity = round_step_size(BUY_AMOUNT / historical_data['close'][-1], STEP_SIZE)
            print("Setup position for %s %s at price %s" % (
                    quantity, TRADE_SYMBOL, historical_data['close'][-1]))
            filled_quantity, avg_price = order_market(TRADE_SYMBOL, quantity, "BUY")
            print(filled_quantity)
            if filled_quantity > 0:
                in_position = True
                entry_time = candle['t']


if __name__ == "__main__":
    run = Runner(schedule)
    run.run_forever()
