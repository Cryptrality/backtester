from enum import Enum
from datetime import datetime, timedelta, timezone
from cryptrality.misc import str_to_minutes, candle_close_timestamp



class RunnerClass(object):
    '''
    This is a singleton pattern
    '''
    _instance = None
    messages = []
    current_time = None
    positions = {}
    step_size = {}
    price_precision = {}
    portfolio = {}
    current_price = {}
    historical_klines = {}
    plot_data = {}
    plot_config = {}


    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            print('Creating The Singleton Runner')
            cls._instance = super(RunnerClass, cls).__new__(
                cls, *args, **kwargs)
            # Put any initialization here.
        return cls._instance

    def get_candles(self, start, end):
        '''empty method, each exchange should implement its own version'''
        self.klines = []

    def update_executions(self, timestamp, now=False):
        '''
        Reading the opening time of the receiving candles, it stores the earlier
        time in which a candle will close (eg in presence of multiple timeframe)
        and copute which of the timeframes used in the strategy will close at that
        given time.
        NOTE: this approach will prevent execution of the strategy is some missing
        data is encountered. Skipping an execution will stop the strategy to run
        '''
        date = datetime.utcfromtimestamp(
            timestamp / 1000)
        next_time = None
        intervals = []
        if now:
            next_time = date
        else:
            for schedule in self.schedule:
                delta_minutes = timedelta(minutes=str_to_minutes(schedule['interval']))
                if next_time is None:
                    next_time = date + delta_minutes
                else:
                    other_time = date + delta_minutes
                    if other_time < next_time:
                        next_time = other_time
        all_minutes = (next_time.hour * 60) + next_time.minute
        for schedule in self.schedule:
            if all_minutes % schedule['interval_minutes'] == 0:
                intervals.append(schedule['interval'])
        self.next_execution = {
            'timestamp': int(
                next_time.replace(tzinfo=timezone.utc).timestamp() * 1000),
            'intervals': intervals
            }

    def check_executions(self, timestamp):
        '''
        Check if the execution of handlers is possible by checking if the
        timestamp of the next scheduled execution is equal to the timestamp
        of the candles in the dataset
        '''
        if timestamp > self.next_execution['timestamp']:
            self.update_executions(timestamp)
        responses = []
        for schedule in self.schedule:
            if schedule['interval'] in self.next_execution['intervals']:
                for symbol in schedule['symbols']:
                    try:
                        kline_data = self.historical_klines[
                            schedule['interval']][symbol]
                        responses.append(self.next_execution[
                            'timestamp'] == candle_close_timestamp(
                                kline_data['timestamp'][-1], schedule['interval']))
                    except KeyError:
                        pass
        if len(responses) > 0:
            return all(responses)
        else:
            return False


class State(object):
    pass


def makeScheduler():
    ''' define interval, symbol and number of cadles available '''
    handler = []
    def schedule(interval, symbols, window_size=500):
        def handlers(fn):
            handler.append(
                {
                    'name': fn.__name__,
                    'fn': fn,
                    'interval': interval,
                    'symbols': symbols,
                    'window_size': window_size
                }
            )
            return fn
        return handlers
    schedule.all =  handler
    return schedule


schedule = makeScheduler()



class Order(object):

    def __init__(self, id, symbol, type, side, quantity, limit_price=None, status=1, trigger_side=None):
        self.id = id
        self.link_id = None
        self.type = OrderType(type)
        self.symbol = symbol
        self.side = OrderSide(side)
        self.quantity = quantity
        self.filled_quantity = 0
        self.status = OrderStatus(status)
        self.close_position = False
        self.limit_price = limit_price
        self.stop_price = None
        self.created_time = None
        self.error = None
        self.fees_asset = None
        self.fills = None
        self.leverage = None
        self.executed_quantity = None
        self.executed_price = None
        self.executed_time = None
        self.fees = 0
        if trigger_side is None:
            if self.side == OrderSide.Buy:
                self.trigger_side = -1
            elif self.side == OrderSide.Sell:
                self.trigger_side = 1
        else:
            self.trigger_side = trigger_side
        self.limit_fallback_action = None
        self.limit_fallback_start_from = 'created'
        self.limit_timer_start = None
        self.limit_fallback_seconds = None
        self.fills_when_canceled = False
    
    def setup_fallback_action(self, action, start_from, fallback_seconds):
        self.limit_fallback_action = action
        self.limit_fallback_start_from = start_from
        self.limit_fallback_seconds = fallback_seconds

    def check_limit_timer(self, current_time):
        if self.limit_fallback_seconds:
            if self.limit_fallback_action:
                if self.limit_fallback_start_from == 'created':
                    self.limit_timer_start = self.created_time
                elif self.limit_fallback_start_from == 'filled':
                    if self.limit_timer_start is None:
                        if self.status == OrderStatus.PartiallyFilled:
                            self.limit_timer_start = RunnerClass.current_time
                if self.limit_timer_start:
                    date_start = datetime.utcfromtimestamp(
                        self.limit_timer_start / 1000)
                    date_now = datetime.utcfromtimestamp(
                        current_time / 1000)
                    if (date_now - date_start) >= timedelta(seconds=self.limit_fallback_seconds):
                        return True
        return False

    def is_placed(self):
        return self.status == OrderStatus(1)

    def is_pending(self):
        return self.status == OrderStatus(2)

    def is_partially_filled(self):
        return self.status == OrderStatus(3)

    def is_filled(self):
        return self.status == OrderStatus(4)

    def is_canceled(self):
        return self.status == OrderStatus(5)

    def is_rejected(self):
        return self.status == OrderStatus(6)

    def is_error(self):
        return self.status == OrderStatus(8)
    
    def cancel(self):
        self.status = OrderStatus(5)

    def refresh(self):
        pass

    def update_leverage(self, leverage):
        self.leverage = leverage

    def update_trigger_mode(self, trigger_with):
        self.trigger_with = trigger_with

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

class PositionStatus(Enum):
    Created = 1
    Open = 2
    Close = 3

class OrderStatus(Enum):
    Created = 1
    Pending = 2
    PartiallyFilled = 3
    Filled = 4
    Canceled = 5
    Rejected = 6
    Expired = 7
    Error = 8
    BarrierTouched = 9
    StopTriggered = 10


class OrderSide(Enum):
    Buy = 0
    Sell = 1

class OrderType(Enum):
    Market = 0
    Limit = 1
    IfTouched = 2
    StopMarket = 3
    StopLimit = 4
    MakerLimit = 5

class Position(object):

    def __init__(self, symbol, quantity, price):
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.exit_price = None
        self.entry_time = None
        self.exit_time = None
        self.pnl = 0
        self.status = PositionStatus(1)
        self.is_closed = None
        self.is_open = None
        self.orders = []

    def open(self, timestamp):
        self.status = PositionStatus(2)
        self.is_closed = False
        self.is_open = True
        self.entry_time = timestamp

    def close(self):
        self.status = PositionStatus(3)
        self.is_closed = True
        self.is_open = False
        '''check the orders if any is left open'''

    def update(self, quantity, timestamp, price):
        self.quantity = quantity
        self.price = price
        if self.status ==  PositionStatus.Created and self.quantity != 0:
            self.open(timestamp)

    def add_order(self, order):
        self.orders.append(order)

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

def plot(symbol, x):
    try:
        RunnerClass.plot_data[symbol].append(x)
    except KeyError:
        RunnerClass.plot_data[symbol] = [x]


def plot_config(config):
    RunnerClass.plot_config = config
