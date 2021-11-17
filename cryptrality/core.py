import json
#from cryptrality.misc import round_time

"""
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
"""



def makeScheduler():
    ''' define interval, symbol and number of cadles available '''
    handler = []
    def schedule(interval, symbol, window_size=100):
        def handlers(fn):
            handler.append(
                {
                    'name': fn.__name__,
                    'fn': fn,
                    'interval': interval,
                    'symbols': symbol,
                    'window_size': window_size
                }
            )
            return fn
        return handlers
    schedule.all =  handler
    return schedule


schedule = makeScheduler()