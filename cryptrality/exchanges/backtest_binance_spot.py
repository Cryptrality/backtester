import json
import numpy
import talib
import os
import random
from datetime import datetime, timedelta
from binance.helpers import round_step_size
from binance.client import Client
from binance.enums import *
from cryptrality.misc.utils import round_time, str_to_minutes


DATE_START = os.environ['DATE_START']
DATE_END = os.environ['DATE_END']
API_KEY = os.environ['BINANCE_API_KEY']
API_SECRET = os.environ['BINANCE_API_SECRET']

try:
    SLIPPAGE = float(os.environ['SLIPPAGE'])
except KeyError:
    SLIPPAGE = 0.0015


try:
    CACHED_KLINES_PATH = float(os.environ['CACHED_KLINES_PATH'])
except KeyError:
    CACHED_KLINES_PATH = 'cached_klines'


client = Client(API_KEY, API_SECRET)


class FakeWS:

    def __init__(self):
        self.data = None
    
    def send(self, data):
        self.data = json.loads(data)

class Position:

    def __init__(self, symbol):
        self.symbol = symbol
        self.positionAmt = 0
        self.entryPrice = 0
        self.markPrice = 0
        self.unRealizedProfit = 0
        self.liquidationPrice = 0
        self.leverage = 0

    def create_position(self, amount, leverage):
        self.positionAmt = amount
        self.entryPrice = Runner.current_price[self.symbol]
        self.leverage = leverage
        self.markPrice = Runner.current_price[self.symbol]
    
    def update_profit(self):
        self.markPrice = Runner.current_price[self.symbol]
        used_q = self.positionAmt * self.entryPrice
        current_q = self.positionAmt * self.markPrice
        self.unRealizedProfit = current_q - used_q

    def close_position(self):
        self.positionAmt = 0
        self.entryPrice = 0
        self.unRealizedProfit = 0
        self.liquidationPrice = 0
        self.leverage = 0

    def return_data(self):
        try:
            info = {
                'symbol': self.symbol,
                'positionAmt': self.positionAmt,
                'entryPrice': self.entryPrice,
                'markPrice': self.markPrice,
                'unRealizedProfit': self.unRealizedProfit,
                'liquidationPrice': 0,
                'leverage': self.leverage}
        except KeyError:
            info = {
                'symbol': self.symbol,
                'positionAmt': 0,
                'entryPrice': 0,
                'markPrice': 0,
                'unRealizedProfit': 0,
                'liquidationPrice': 0,
                'leverage': 0}
        return [info]


def load_klines_from_file(file_name):
    klines_data = []
    with open(file_name, 'rt') as kline_in:
        for kline in kline_in:
            klines_data.append(kline.strip().split(','))
    return klines_data


def write_klines_to_file(klines_data, file_name):
    with open(file_name, 'wt') as kline_out:
        for kline in klines_data:
            kline_out.write('%s\n' % ','.join(map(str,kline)))


class Runner:
    ## little hack. Use the global in the Runner class
    ## to store current close value
    current_price = {}
    current_time = None
    position = {}
    orders = []
    step_size = {}

    def __init__(self, data_info, on_error, on_open, on_close, on_message):
        self.data_info = data_info
        self.on_error = on_error
        self.on_open = on_open
        self.on_close = on_close
        self.on_message = on_message
        self.ws = FakeWS()
        self.klines = None
    
    def __gater_data(self):
        self.on_open(self.ws)
        symbols = []
        periods = []
        historical_data = {}
 
        for param in self.ws.data['params']:
            symbol, stream_type = param.split('@')
            symbol = symbol.upper()
            if symbol not in symbols:
                symbols.append(symbol)
            if stream_type.startswith('kline'):
                periods.append(stream_type.split('_')[1])
        for symbol in symbols:
            self.position[symbol] = Position(symbol)
            historical_data[symbol] = {}
            for period in periods:
                klines_data_name = os.path.join(
                    CACHED_KLINES_PATH, '%s.csv' % '_'.join(
                        [symbol, period, DATE_START.replace('-', '_'), DATE_END.replace('-', '_')]))
                if not os.path.exists(CACHED_KLINES_PATH):
                    os.makedirs(CACHED_KLINES_PATH)
                min_period = str_to_minutes(period)
                date_object1 = datetime.strptime(
                    DATE_START, "%d-%m-%y")
                date_object2 = datetime.strptime(
                    DATE_END, "%d-%m-%y")
                from_time = round_time(date_object1,
                    round_to=60*min_period)
                to_time = round_time(date_object2,
                    round_to=60*min_period)
                ts = int(from_time.timestamp()) * 1000
                ts2 = int(to_time.timestamp()) * 1000
                if os.path.exists(klines_data_name) and os.path.isfile(klines_data_name):
                    start_data = load_klines_from_file(klines_data_name)

                else:
                    start_data = client.get_historical_klines(
                        symbol, period, start_str=ts, end_str=ts2)
                    write_klines_to_file(start_data, klines_data_name)
                historical_data[symbol][period] = list(
                    (list_to_klines(candle, symbol, period) for candle in start_data))
        self.klines = sync_klines(historical_data)

    def run_forever(self):
        self.__gater_data()
        for k in self.klines:
            Runner.current_price[k['k']['s']] = float(
                k['k']['c'])
            Runner.position[k['k']['s']].update_profit()
            Runner.current_time = k['E']
            while len(Runner.orders) > 0:
                o = Runner.orders.pop(0)
                self.on_message(self.ws, json.dumps(o))
            self.on_message(self.ws, json.dumps(k))


def list_to_klines(item, symbol, period_str):
    kline = {'E': int(item[0]),
        'e': 'kline',
        'k': {'B': '0',
            'L': item[11],
            'Q': item[9],
            'T': int(item[6]),
            'V': item[10],
            'c': item[4],
            'f': item[11],
            'h': item[2],
            'i': period_str,
            'l': item[3],
            'n': int(item[8]),
            'o': item[1],
            'q': item[7],
            's': symbol,
            't': int(item[0]),
            'v': item[5],
            'x': True},
        's': symbol}
    return kline

def order_trade_update(symbol, amount, side, price, timestamp):
    id = ''.join(map(str, random.sample(range(10), 10)))
    order_new = {
        'e': 'ORDER_TRADE_UPDATE',
        'T': timestamp,
        'E': timestamp,
        'o': {
            's': symbol,
            'c': '123abcXYZabc321XYZ',
            'S': side,
            'o': 'MARKET',
            'f': 'GTC',
            'q': amount,
            'p': '0',
            'ap': '0',
            'sp': '0',
            'x': 'NEW',
            'X': 'NEW',
            'i': id,
            'l': '0',
            'z': '0',
            'L': '0',
            'T': timestamp,
            't': 0,
            'b': '0',
            'a': '0',
            'm': False,
            'R': False,
            'wt': 'CONTRACT_PRICE',
            'ot': 'MARKET',
            'ps': 'BOTH',
            'cp': False
        }
    }
    
    order_filled = {
        'e': 'ORDER_TRADE_UPDATE',
        'T': timestamp,
        'E': timestamp,
        'o': {
            's': symbol,
            'c': '123abcXYZabc321XYZ',
            'S': side,
            'o': 'MARKET',
            'f': 'GTC',
            'q': amount,
            'p': '0',
            'ap': '0',
            'sp': '0',
            'x': 'TRADE',
            'X': 'FILLED',
            'i': id,
            'l': '0',
            'z': '0',
            'L': price,
            'T': timestamp,
            't': 0,
            'b': '0',
            'a': '0',
            'm': False,
            'R': False,
            'wt': 'CONTRACT_PRICE',
            'ot': 'MARKET',
            'ps': 'BOTH',
            'cp': False
        }
    }

    return (id, order_new, order_filled)


def sync_klines(klines_periods):
    klines_list = []
    for symbol in klines_periods:
        for period in klines_periods[symbol]:
            klines_list += klines_periods[symbol][period]
    klines_list.sort(key=lambda x: datetime.fromtimestamp(x['k']['t'] / 1000))
    for kline in klines_list:
        yield kline

def socket_url(symbol, klines):
    url = "wss://fstream.binance.com/ws"
    channels = []
    for kline in klines:
        channels.append('%s@kline_%s' % (symbol.lower(), kline))
    return (url, channels)


def get_index_from_data(candles_list, i=4):
    for candle in candles_list:
        yield float(candle[i])

def get_balance_quoted_asset(asset):
    return {'locked': 0, 'free': 1000}


def get_position(symbol, side="SHORT"):
    amount = 0
    position_data = None
    try:
        postion_obj = Runner.position[symbol]
    except:
        postion_obj = Position(symbol)
    all_positions = postion_obj.return_data()
    for position in all_positions:
        if side == "LONG":
            if float(position['positionAmt']) > amount:
                amount = float(position['positionAmt'])
                position_data = position
        elif side == "SHORT":
            if float(position['positionAmt']) < amount:
                amount = float(position['positionAmt'])
                position_data = position
    if position_data is None:
        position = all_positions[0]
        if float(position['positionAmt']) == 0:
            position_data = position
    return (amount, position_data)



def last_price(symbol):
    try:
        return Runner.current_price[symbol]
    except KeyError:
        return 0


def get_step_size(symbol):
    futures_info = client.get_exchange_info()
    step_size = None
    for s in  futures_info["symbols"]:
        if s["symbol"] == symbol:
            for filter in s['filters']:
                if filter['filterType'] == 'LOT_SIZE':
                    step_size = float(filter['stepSize'])
                    break
    return step_size


def get_historical_klines(symbol, period_nr, period_str, nr_candles=50):

    current_ts = Runner.current_time
    if current_ts is None:
        historical_data = {
            'open' : [],
            'close' : [],
            'high' : [],
            'low' : []}
        return historical_data
    start_time = round_time(datetime.fromtimestamp(float(current_ts) / 1000),
        round_to=60*period_nr) - timedelta(minutes=period_nr * (2 * nr_candles))
    ts = int(start_time.timestamp()) * 1000
    start_data = client.get_historical_klines(symbol, period_str, start_str=ts)
    historical_data = {
        'open' : list(get_index_from_data(start_data, 1))[:-1],
        'close' : list(get_index_from_data(start_data, 4))[:-1],
        'high' : list(get_index_from_data(start_data, 2))[:-1],
        'low' : list(get_index_from_data(start_data, 3))[:-1]}
    return historical_data

def order_market(symbol, quantity, side='BUY', leverage=1):
    print("symbol: %s, side: %s, amount %s" % (symbol, side, quantity))

    position = Runner.position[symbol]
    if side == 'SELL':
        quantity = -1 * quantity
    pos_amount = position.positionAmt

    if pos_amount + quantity == 0:
        position.close_position()
    else:
        position.create_position(pos_amount + quantity, leverage)
    
    filled_quantity = abs(quantity)
    avg_price = position.markPrice
    id, order_new, order_filled = order_trade_update(
        symbol, quantity, side, avg_price, Runner.current_time)
    Runner.orders += [order_new, order_filled]
    # wait for the order to fill
    print('Order filled')
    return map(float, (filled_quantity, avg_price))



def print_position_info(symbol, stop_loss, side='LONG'):
    max_position_amount, max_position_data = get_position(
        symbol, side)
    position_message = (
        "Position for %(symbol)s, entry price %(entry)s "
        "with leverage %(leverage)sx, "
        "liquidation price %(liquidation)s, mark price %(mark)s, "
        "stop loss %(stop_loss)s, "
        "unrealized Profit %(pnl)s")
    return position_message % {
        "symbol": symbol,
        "leverage": max_position_data["leverage"],
        "entry": max_position_data["entryPrice"],
        "liquidation": max_position_data["liquidationPrice"],
        "mark": max_position_data["markPrice"],
        "stop_loss": stop_loss,
	        "pnl": max_position_data["unRealizedProfit"]
    }
