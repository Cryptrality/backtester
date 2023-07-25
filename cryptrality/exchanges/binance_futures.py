from asyncio.log import logger
from datetime import datetime, timedelta
from binance.helpers import round_step_size
from binance.client import Client
from binance import ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException
from cryptrality.misc import round_time, str_to_minutes, candle_close_timestamp
from cryptrality.core import (
    RunnerClass,
    OrderSide,
    OrderType,
    OrderStatus,
    Order,
    Position,
)
import cryptrality.exchanges.binance_common as bc
from cryptrality.__config__ import Api
from threading import Thread
from queue import Queue
from time import sleep
import numpy as np


api = Api()


if api.BINANCE_API_KEY is None or api.BINANCE_API_SECRET is None:
    print("WARNING: proceeding without Binance client auth")
else:
    client = Client(api.BINANCE_API_KEY, api.BINANCE_API_SECRET)


class OrderBinanceFutures(Order):
    def cancel(self, cancel_time=None):
        status = False
        if self.type in [OrderType.Limit, OrderType.Market]:
            if self.cancel_time:
                attempt_time = datetime.utcfromtimestamp(
                    self.cancel_time / 1000
                )
                current_time = datetime.utcfromtimestamp(
                    Runner.current_time / 1000
                )
                if (current_time - attempt_time) <= timedelta(seconds=5):
                    logger.warning(
                        "%s: Skip repetition of cancellation attempt for order %i"
                        % (self.symbol, self.id)
                    )
                    return status
            try:
                status = cancel_order(self.symbol, self.id)
            except BinanceAPIException as e:
                Runner.loggers["main"].error(
                    "failed to cancel order %s for %s. "
                    % (self.id, self.symbol)
                )
                Runner.loggers["main"].error(e)
                last_orders = client.futures_get_all_orders(
                    symbol=self.symbol, limit=20
                )
                order_match = [
                    order
                    for order in last_orders
                    if order["orderId"] == self.id
                ]
                if len(order_match) == 1:
                    if order_match[0]["status"] == "CANCELED":
                        Runner.loggers["main"].info(
                            "Retrived CANCELED status for order %s for %s  "
                            % (self.id, self.symbol)
                        )
                        self.status = OrderStatus.Canceled
                        status = True
                    elif order_match[0]["status"] == "FILLED":
                        self.status = OrderStatus.Filled
                        Runner.loggers["main"].info(
                            "Retrived FILLED status for order %s for %s  "
                            % (self.id, self.symbol)
                        )

                return False
        else:
            self.status = OrderStatus.Canceled
            return True
        if cancel_time:
            self.cancel_time = cancel_time
        return status


class Runner(RunnerClass):
    """
    A class that coordinate the websocket stream, store, check anv validate ochl data
    and various information and synchronize the execution of the strategy handlers
    """

    def __init__(self) -> None:
        super().__init__()
        RunnerClass.max_plot_data = 3000
        self.ws = ThreadedWebsocketManager(
            api_key=api.BINANCE_API_KEY, api_secret=api.BINANCE_API_SECRET
        )
        self.handler_queue = Queue()

    @staticmethod
    def handler_worker_func(q, state):
        """Execute an handler function

        :param q: Queue to get the jobs to execute
        :type q: queue.Queue
        :param state: The global state object
        :type state: State
        """
        while True:
            handler_fn, data_map, interval = q.get()
            handler_fn(state, data_map)
            symbols = " ".join(data_map.keys())
            Runner.loggers["exec"].info(
                "Exec function %s for interval %s "
                "with symbols %s" % (handler_fn.__name__, interval, symbols)
            )

    def setup_data(self, schedule, state):
        """
        Read the schedule decorator from the strategy code and initialize the
        connection with the websocket, subscribing to the requested channels,
        and setup the execution schedule for each handlers
        """
        self.state = state
        self.schedule = []
        self.next_execution = {"timestamp": None, "intervals": []}
        channels = []
        for param in schedule:
            period_info = {
                "interval": param["interval"],
                "interval_minutes": str_to_minutes(param["interval"]),
                "symbols": [],
                "window_size": param["window_size"],
                "fn": param["fn"],
            }
            symbols = param["symbols"]
            if isinstance(symbols, str):
                period_info["symbols"].append(symbols)
            elif isinstance(symbols, list):
                for symbol in symbols:
                    if symbol not in period_info["symbols"]:
                        period_info["symbols"].append(symbol)
            self.schedule.append(period_info)
            self.trading_pairs += period_info["symbols"]
        self.trading_pairs = list(set(self.trading_pairs))
        channel_str = "%(symbol)s@kline_%(interval)s"

        for interval in self.schedule:
            for symbol in interval["symbols"]:
                channels.append(
                    channel_str
                    % {
                        "symbol": symbol.lower(),
                        "interval": interval["interval"],
                    }
                )
        self.handler_worker = Thread(
            target=self.handler_worker_func,
            args=(self.handler_queue, self.state),
            daemon=True,
        )
        self.ws.start()
        self.user_data_socket = self.ws.start_futures_socket(
            callback=self.user_data_handler
        )
        self.multiplex = self.ws.start_futures_multiplex_socket(
            self.aggregate_candle, streams=channels
        )
        self.handler_worker.start()

    def aggregate_candle(self, k):
        """
        Read the kline stream messages from the websocket.
        At every update (lso intra-candle) check if an order was setup
        to trigger at current price.
        if the message is a "candle close" message, execute the strategy
        handlers when the dataset of all symbols is complete.
        If there are more timeframe in the strategy, the scheduling algorithm
        will execute the handlers in the same order as in the strategy script
        (top to bottom)
        """
        try:
            candle = k["data"]["k"]
            Runner.current_time = k["data"]["E"]

        except KeyError:

            try:
                error = k["e"] == "error"
                if error:
                    channels = []
                    channel_str = "%(symbol)s@kline_%(interval)s"
                    for interval in self.schedule:
                        for symbol in interval["symbols"]:
                            channels.append(
                                channel_str
                                % {
                                    "symbol": symbol.lower(),
                                    "interval": interval["interval"],
                                }
                            )
                    Runner.loggers["main"].warning(
                        "attempting to restart the kline streams for %s"
                        % channels
                    )
                    self.ws.stop_socket(self.multiplex)
                    sleep(3)
                    self.multiplex = self.ws.start_futures_multiplex_socket(
                        self.aggregate_candle, streams=channels
                    )
            except KeyError:
                pass
            Runner.loggers["main"].warning(k)
            return
        current_interval = candle["i"]
        current_symbol = candle["s"]
        candle_close = candle["x"]
        Runner.current_price[current_symbol] = float(candle["c"])
        self.candle_data_handler(candle)
        if candle_close:
            candle_close_time = candle_close_timestamp(
                candle["t"], current_interval
            )
            if self.next_execution["timestamp"] is None:
                self.update_executions(candle_close_time, now=True)
            for schedule in self.schedule:
                if schedule["interval"] == current_interval:
                    if current_symbol in schedule["symbols"]:
                        try:
                            # update data
                            Runner.historical_klines[current_interval][
                                current_symbol
                            ] = self.update_ochl(
                                Runner.historical_klines[current_interval][
                                    current_symbol
                                ],
                                candle,
                                schedule["window_size"],
                            )
                        except KeyError:
                            # init data
                            past_klines = get_historical_klines(
                                current_symbol,
                                current_interval,
                                nr_candles=schedule["window_size"],
                            )
                            past_ochl = self.init_ochl(
                                past_klines, schedule["window_size"]
                            )
                            if candle["t"] == past_ochl["timestamp"][-1]:
                                Runner.historical_klines[current_interval][
                                    current_symbol
                                ] = past_ochl
                            else:
                                try:
                                    Runner.historical_klines[current_interval][
                                        current_symbol
                                    ] = self.update_ochl(
                                        past_ochl,
                                        candle,
                                        schedule["window_size"],
                                    )
                                except KeyError:
                                    Runner.historical_klines[
                                        current_interval
                                    ] = {}
                                    Runner.historical_klines[current_interval][
                                        current_symbol
                                    ] = self.update_ochl(
                                        past_ochl,
                                        candle,
                                        schedule["window_size"],
                                    )
            # Check for execution
            if self.check_executions(candle_close_time):
                for schedule in self.schedule:
                    if (
                        schedule["interval"]
                        in self.next_execution["intervals"]
                    ):
                        data_map = {}
                        for symbol in schedule["symbols"]:
                            try:
                                data_map[symbol] = Runner.historical_klines[
                                    schedule["interval"]
                                ][symbol]
                            except KeyError:
                                data_map[symbol] = None
                        self.handler_queue.put(
                            (schedule["fn"], data_map, schedule["interval"])
                        )
                self.update_executions(candle_close_time)

    def user_data_handler(self, k):
        """
        Handlers for the user streams, it receive and parse position information, orders
        status information and configuration information (eg leverage changes)
        Depending on the message it will add or close position object in the symbol position
        list, update and react to order filling status update.
        """

        try:
            message_type = k["e"]
            Runner.current_time = k["E"]
        except KeyError:
            message_type = None
        # Receive Positions/Orders/Config update here
        # Interact with object in the singleton
        # Maybe convert to a dedicated DB later on
        if message_type == "ACCOUNT_UPDATE":
            # Position info here
            event_time = datetime.fromtimestamp(Runner.current_time / 1000)
            try:
                positions_info = k["a"]["P"]
            except KeyError:
                pass
            Runner.loggers["main"].info(k)
            if len(positions_info) > 0:
                position = positions_info[0]
                symbol = position["s"]
                if symbol not in self.trading_pairs:
                    return
                position_amount = float(position["pa"])
                entry_price = float(position["ep"])
                try:
                    last_position = Runner.positions[symbol][-1]
                except KeyError:
                    Runner.positions[symbol] = []
                    last_position = None
                except IndexError:
                    last_position = None
                if (
                    last_position
                    and last_position.is_open
                    and position_amount == 0
                ):
                    # closing last position
                    last_position.close()
                else:
                    # create/update new position
                    add_position = False
                    if last_position:
                        if last_position.is_closed:
                            add_position = True
                        else:
                            last_position.update(
                                position_amount,
                                Runner.current_time,
                                entry_price,
                            )
                    else:
                        add_position = True

                    if add_position:
                        new_position = Position(
                            symbol, position_amount, entry_price
                        )
                        new_position.open(Runner.current_time)
                        Runner.positions[symbol].append(new_position)
                    else:
                        Runner.positions[symbol][-1] = last_position
        elif message_type == "ORDER_TRADE_UPDATE":
            event_time = datetime.fromtimestamp(Runner.current_time / 1000)
            order_id = k["o"]["i"]
            symbol = k["o"]["s"]
            if symbol not in self.trading_pairs:
                return
            order_side_str = k["o"]["S"]
            order_quantity = float(k["o"]["q"])
            if order_side_str == "SELL":
                order_side = 1
            elif order_side_str == "BUY":
                order_side = 0
            try:
                last_position = Runner.positions[symbol][-1]
            except KeyError:
                Runner.positions[symbol] = []
                last_position = None
            except IndexError:
                last_position = None

            if last_position is None:
                Runner.loggers["main"].warning("Create a new position obj")
                last_position = Position(symbol, 0, None)
                self.positions[symbol].append(last_position)

            orders_ids = [o.id for o in last_position.orders]

            try:
                updated_order = orders_ids.index(order_id)
            except ValueError:
                updated_order = None

            if updated_order is None:
                Runner.loggers["main"].warning(
                    "Order %i for symbol %s is not recorder "
                    "in the system, create a new order" % (order_id, symbol)
                )
                updated_order = OrderBinanceFutures(
                    order_id, symbol, 0, order_side, order_quantity
                )
                updated_order.created_time = Runner.current_time
                last_position.pnl += float(k["o"]["rp"])
                last_position.add_order(updated_order)
            else:
                order_status = k["o"]["X"]
                new_status = OrderStatus(
                    bc.order_status_msg_to_enum[order_status]
                )
                filled_quantity = float(k["o"]["z"])
                order_time = int(k["o"]["T"])
                order_price = float(k["o"]["ap"])

                last_position.orders[updated_order].status = new_status
                last_position.orders[
                    updated_order
                ].filled_quantity = filled_quantity
                last_position.orders[updated_order].created_time = order_time
                last_position.orders[
                    updated_order
                ].executed_price = order_price
                last_position.pnl += float(k["o"]["rp"])
                if new_status == OrderStatus.Filled:
                    if last_position.orders[updated_order].close_position:
                        last_position.exit_price = order_price
                        last_position.exit_time = Runner.current_time

        elif message_type == "ACCOUNT_CONFIG_UPDATE":
            # leverage info here
            try:
                event_time = datetime.fromtimestamp(Runner.current_time / 1000)
                update_leverage = k["ac"]["l"]
                symbol = k["ac"]["s"]
                if symbol not in self.trading_pairs:
                    return
                Runner.loggers["main"].info(
                    "%s Update leverage to %iX for symbol %s"
                    % (event_time, update_leverage, symbol)
                )
            except KeyError:
                pass
        elif message_type is None:
            try:
                error = k["e"] == "error"
                if error:
                    Runner.loggers["main"].error(
                        "attempting to restart the used data stream"
                    )
                    self.ws.stop_socket(self.user_data_socket)
                    sleep(3)
                    self.user_data_socket = self.ws.start_futures_socket(
                        callback=self.user_data_handler
                    )
            except KeyError:
                pass
            Runner.self.warning(k)

    @staticmethod
    def candle_data_handler(candle):
        """
        Check for orders limits at every update.
        This handles if_touched orders, where the limit is specified in the order
        object, if the limit is breached in the specified direction a market (or limit)
        order is sent to the exchange.

        This handler will also check for limit expiration (eg set the limit expires
        after 10 second than need to be cancelled, and eventually filled with a market
        order)
        """

        # Candle handling starts here
        current_symbol = candle["s"]

        # In live trading here we could check for market stop orders
        # set in the bots (not registered to the exchange)
        # hence we also need an abstract method to trigger the
        # order: We need an Order object as well
        try:
            last_position = Runner.positions[current_symbol][-1]
        except KeyError:
            last_position = None
        except IndexError:
            last_position = None
        if last_position is None or last_position.is_closed:
            return
        types_to_monitor = [
            OrderType.IfTouched,
            OrderType.Limit,
            OrderType.MakerLimit,
        ]
        status_to_monitor = [
            OrderStatus.Created,
            OrderStatus.PartiallyFilled,
            OrderStatus.Pending,
        ]
        for i, order in enumerate(last_position.orders):
            if order.type in types_to_monitor:
                if order.type == OrderType.Limit and order.fills_when_canceled:
                    leftover_quantity = abs(order.quantity) - abs(
                        order.filled_quantity
                    )
                    if order.side == OrderSide.Sell:
                        leftover_quantity = -1 * leftover_quantity
                    order_market_amount(
                        order.symbol, leftover_quantity, order.leverage
                    )
                    order.fills_when_canceled = False
                if order.status not in status_to_monitor:
                    continue
                quantity = order.quantity
                trigger_side = order.trigger_side
                if order.type == OrderType.Limit:
                    canceled = False
                    if order.check_limit_timer(Runner.current_time):
                        canceled = order.cancel(Runner.current_time)
                    if (
                        canceled
                        and order.limit_fallback_action == "fill_market"
                    ):
                        order.fills_when_canceled = True
                    continue
                check_iftouched = False
                if trigger_side and order.type == OrderType.IfTouched:
                    if trigger_side == 1:
                        if float(candle["c"]) > order.limit_price:
                            check_iftouched = True
                    elif trigger_side == -1:
                        if float(candle["c"]) < order.limit_price:
                            check_iftouched = True
                else:
                    pass
                if check_iftouched:
                    order.status = OrderStatus(10)
                    if order.trigger_with == "market":
                        if order.side == OrderSide.Buy:
                            order_market_amount(
                                current_symbol, abs(quantity), order.leverage
                            )
                        elif order.side == OrderSide.Sell:
                            order_market_amount(
                                current_symbol,
                                -1 * abs(quantity),
                                order.leverage,
                            )
                    elif order.trigger_with == "limit":
                        fallback = None
                        if order.limit_fallback_action:
                            if order.limit_fallback_start_from:
                                if order.limit_fallback_seconds:
                                    fallback = {
                                        "action": order.limit_fallback_action,
                                        "start_from": order.limit_fallback_start_from,
                                        "fallback_seconds": order.limit_fallback_seconds,
                                    }
                        if order.side == OrderSide.Buy:
                            order_limit_amount(
                                current_symbol,
                                abs(quantity),
                                order.limit_price,
                                order.leverage,
                                fallback,
                            )
                        elif order.side == OrderSide.Sell:
                            order_limit_amount(
                                current_symbol,
                                -1 * abs(quantity),
                                order.limit_price,
                                order.leverage,
                                fallback,
                            )

    @staticmethod
    def init_ochl(candles, max_len):
        """
        Read the historical candle data and return a dictionary,
        in which every key is a numpy array synchronized by index.

        NOTE: this can be changed by using a smarter object and/or
        a panda DataFrame of numpy multi dimensional array.
        """
        kline_dict = {
            "timestamp": "t",
            "open": "o",
            "close": "c",
            "high": "h",
            "low": "l",
            "volume": "v",
        }
        historical_klines = {}
        for k in candles:
            candle = k["k"]
            for key, value in kline_dict.items():
                try:
                    historical_klines[key] = np.append(
                        historical_klines[key], float(candle[value])
                    )
                    historical_klines[key] = historical_klines[key][-max_len:]
                except KeyError:
                    historical_klines[key] = np.array(
                        [float(candle[value])], dtype=float
                    )
        return historical_klines

    def update_ochl(self, historical_klines, candle, max_len):
        """
        Update the candlestick data ad every new closed candle.
        Check for duplicated candles and for missing data in the dataset.
        In case of duplicate it removes the first entry (keep the last one)
        and in case of missing data it re-init the ochl data with an additional
        API call
        """
        period_str = candle["i"]
        symbol = candle["s"]
        period_nano_seconds = np.timedelta64(
            str_to_minutes(period_str) * 60 * 1000000
        )
        zero_seconds = np.timedelta64(0)
        kline_dict = {
            "timestamp": "t",
            "open": "o",
            "close": "c",
            "high": "h",
            "low": "l",
            "volume": "v",
        }
        for key, value in kline_dict.items():
            try:
                historical_klines[key] = np.append(
                    historical_klines[key], float(candle[value])
                )
                historical_klines[key] = historical_klines[key][-max_len:]
            except KeyError:
                historical_klines[key] = np.array(
                    [float(candle[value])], dtype=float
                )
        if len(historical_klines["timestamp"]) == 1:
            return historical_klines
        check_last = 10
        ts_diff = np.diff(
            np.array(
                list(
                    map(
                        np.datetime64,
                        list(
                            map(
                                datetime.utcfromtimestamp,
                                historical_klines["timestamp"][-check_last:]
                                / 1000,
                            )
                        ),
                    )
                ),
                dtype=np.datetime64,
            )
        )
        if np.all(ts_diff == period_nano_seconds):
            pass
        elif np.any(ts_diff == zero_seconds):
            ts_bool = ts_diff.astype(bool)
            ts_dup_idx_rel = np.insert(ts_bool, ts_bool.size, True)
            ts_dup_idx = np.insert(
                np.repeat(
                    True, historical_klines["timestamp"].size - check_last
                ),
                historical_klines["timestamp"].size - check_last,
                ts_dup_idx_rel,
            )
            for key, value in historical_klines.items():
                historical_klines[key] = value[ts_dup_idx]
            Runner.loggers["main"].warning("remove duplicated candles")
            Runner.loggers["main"].warning(
                "%s" % historical_klines["timestamp"][-5:]
            )
        elif np.any(ts_diff > period_nano_seconds):
            Runner.loggers["main"].warning("missing data!")
            past_klines = get_historical_klines(
                symbol, period_str, nr_candles=max_len
            )
            historical_klines = self.init_ochl(past_klines, max_len)
            historical_klines = self.update_ochl(
                historical_klines, candle, max_len
            )
        return historical_klines

    def run_forever(self):
        """
        Trigger the multithread websocket to start running until the end of times
        """
        self.ws.join()
        self.handler_queue.join()


def get_historical_klines(symbol, period_str, nr_candles=50):
    """
    API call to retrive a number of historical ochl data of a given
    symbol and timeframe, util current time.
    """
    period_nr = str_to_minutes(period_str)
    start_time = round_time(round_to=60 * period_nr) - timedelta(
        minutes=period_nr * (2 * nr_candles)
    )
    ts = int(start_time.timestamp()) * 1000
    start_data = client.futures_historical_klines(
        symbol, period_str, start_str=ts
    )
    historical_data = [
        bc.list_to_klines(candle, symbol, period_str)
        for candle in start_data[:-2]
    ]
    return historical_data


def get_open_position_api(symbol, side="SHORT"):
    all_positions = client.futures_position_information(symbol=symbol)
    amount = 0
    position_data = None
    for position in all_positions:
        if side == "LONG":
            if float(position["positionAmt"]) > amount:
                amount = float(position["positionAmt"])
                position_data = position
        elif side == "SHORT":
            if float(position["positionAmt"]) < amount:
                amount = float(position["positionAmt"])
                position_data = position
    if position_data is None:
        position = all_positions[0]
        if float(position["positionAmt"]) == 0:
            position_data = position
    return position_data


def get_open_position(symbol, side):
    """
    Return the last long/short open position for a symbol, return
    None otherwise

    NOTE: The command doesn't perform an API call, so open positions
    existing before the start of the bot will not be monitored.
    TODO: Add an API call in case the fist time the position list
    is created
    """
    open_position = None
    try:
        last_positions = Runner.positions[symbol]
        if len(last_positions) > 0:
            last_position = last_positions[-1]
            if last_position.is_open:
                if side == "LONG" and last_position.quantity > 0:
                    open_position = last_position
                elif side == "SHORT" and last_position.quantity < 0:
                    open_position = last_position
    except KeyError:
        Runner.positions[symbol] = []
        position_data = get_open_position_api(symbol, side)
        position_amount = float(position_data["positionAmt"])
        if position_amount == 0:
            pass
        else:
            entry_price = float(position_data["entryPrice"])
            open_position = Position(symbol, position_amount, entry_price)
            open_position.open(Runner.current_time)
            Runner.loggers["main"].info("%s add unclosed position" % symbol)
            Runner.positions[symbol].append(open_position)
    return open_position


def last_price(symbol):
    """
    use the price from the latest websocket update (
    it doesn't call the API for the last price)
    """
    try:
        current_price = Runner.current_price[symbol]
    except KeyError:
        try:
            current_price = float(
                client.futures_symbol_ticker(symbol=symbol)["price"]
            )
            Runner.current_price[symbol] = current_price
        except BinanceAPIException:
            Runner.loggers["main"].error(
                "Error getting current price from the exchange"
            )
            return None
    return current_price


def order_market_amount(symbol, quantity, leverage=None):
    """
    Perform a market order for a given quantity at the specified
    leverage. the quantity is intended as base asset quantity
    if the quantity is negative the order will be a sell order
    if positive a buy order
    """

    try:
        last_position = Runner.positions[symbol][-1]
    except KeyError:
        Runner.positions[symbol] = []
        last_position = None
    except IndexError:
        last_position = None

    close_current_position = False
    if last_position and last_position.is_open:
        if last_position.quantity + quantity == 0:
            close_current_position = True
    else:
        if last_position is None or last_position.is_closed:
            last_position = Position(symbol, 0, None)
            Runner.positions[symbol].append(last_position)

    if quantity > 0:
        order_side = 0
        side_str = "BUY"
    elif quantity < 0:
        order_side = 1
        side_str = "SELL"
    elif quantity == 0:
        Runner.loggers["main"].error(
            "Quantity %s for symbol %s is to low" % (quantity, symbol)
        )
        return None

    if leverage:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    try:
        order_new = client.futures_create_order(
            symbol=symbol, type="MARKET", side=side_str, quantity=abs(quantity)
        )
    except BinanceAPIException as e:
        Runner.loggers["main"].error("API Order Error %s" % e)
        order_new = None
    if order_new:
        order_id = order_new["orderId"]
        Runner.loggers["main"].info("%s order id %s" % (symbol, order_id))
        order = OrderBinanceFutures(order_id, symbol, 0, order_side, quantity)
        order.created_time = Runner.current_time
        if close_current_position:
            order.close_position = True
        Runner.positions[symbol][-1].add_order(order)
    else:
        order = None
    return order


def order_limit_amount(symbol, quantity, price, leverage=None, fallback=None):
    """
    Perform a limit order for a given quantity at the specified
    leverage. the quantity is intended as base asset quantity
    if the quantity is negative the order will be a sell order
    if positive a buy order
    """
    try:
        price_precision = Runner.price_precision[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_futures(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision
    try:
        last_position = Runner.positions[symbol][-1]
    except KeyError:
        Runner.positions[symbol] = []
        last_position = None
    except IndexError:
        last_position = None

    close_current_position = False
    if last_position and last_position.is_open:
        if last_position.quantity + quantity == 0:
            close_current_position = True
    else:
        if last_position is None or last_position.is_closed:
            last_position = Position(symbol, 0, None)
            Runner.positions[symbol].append(last_position)

    if quantity > 0:
        order_side = 0
        side_str = "BUY"
    elif quantity < 0:
        order_side = 1
        side_str = "SELL"
    elif quantity == 0:
        Runner.loggers["main"].error(
            "Quantity %s for symbol %s is to low" % (quantity, symbol)
        )
        return

    if leverage:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    try:
        order_new = client.futures_create_order(
            symbol=symbol,
            type="LIMIT",
            side=side_str,
            quantity=abs(quantity),
            timeInForce="GTC",
            price=round_step_size(price, price_precision),
        )
    except BinanceAPIException as e:
        Runner.loggers["main"].error("API Order Error: %s" % e)
        order_new = None

    if order_new:
        order_id = order_new["orderId"]
        Runner.loggers["main"].info("%s order id %s" % (symbol, order_id))
        order = OrderBinanceFutures(
            order_id, symbol, 1, order_side, quantity, price
        )
        order.created_time = Runner.current_time
        if close_current_position:
            order.close_position = True
        if fallback:
            order.setup_fallback_action(**fallback)
        Runner.positions[symbol][-1].add_order(order)
    else:
        order = None
    return order


def order_market_value(symbol, value, leverage=None):
    """
    Perform a market order for a given value at the specified
    leverage. the value is intended as quoted asset amount.
    If the value is negative the order will be a sell order
    if positive a buy order
    """
    try:
        step_size = Runner.step_size[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_futures(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision
    current_price = last_price(symbol)
    if current_price:
        quantity = round_step_size(value / current_price, step_size)
        order = order_market_amount(symbol, quantity, leverage)
        return order


def order_limit_value(symbol, value, price, leverage=None, fallback=None):
    """
    Perform a limit order for a given value at the specified
    leverage. the value is intended as quoted asset amount.
    If the value is negative the order will be a sell order
    if positive a buy order
    """
    try:
        step_size = Runner.step_size[symbol]
        price_precision = Runner.price_precision[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_futures(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision

    stepped_price = round_step_size(price, price_precision)
    quantity = round_step_size(value / stepped_price, step_size)
    order = order_limit_amount(
        symbol, quantity, stepped_price, leverage, fallback
    )
    return order


def close_position(symbol):
    """
    it will send an order to the exchange to close the current open position

    NOTE: I'm not sure if a symbol can have a long and short position at the
    same time. This mathod assumes there is only 1 position opened
    """
    try:
        last_position = Runner.positions[symbol][-1]
    except KeyError:
        last_position = None
    except IndexError:
        last_position = None

    if last_position and last_position.is_open:
        quantity = -1 * last_position.quantity
        order = order_market_amount(symbol, quantity)
    else:
        Runner.loggers["main"].error("Error: no position to close")
        order = None
    return order


def order_if_touched_amount(
    symbol,
    quantity,
    price_limit,
    leverage=None,
    trigger_side=None,
    trigger_with="market",
    fallback=None,
):
    """
    Set a price limit and once reached at the desired side (trigger_side equal to 1
    is cross under, -1 cross over) if will send a market order to the exchange.
    """
    try:
        last_position = Runner.positions[symbol][-1]
    except KeyError:
        Runner.positions[symbol] = []
        last_position = None
    except IndexError:
        last_position = None

    close_current_position = False
    if last_position and last_position.is_open:
        if last_position.quantity + quantity == 0:
            close_current_position = True
    else:
        if last_position is None or last_position.is_closed:
            last_position = Position(symbol, 0, None)
            Runner.positions[symbol].append(last_position)
    if quantity > 0:
        order_side = 0
    elif quantity < 0:
        order_side = 1
    order = OrderBinanceFutures(
        None, symbol, 2, order_side, quantity, price_limit, 1, trigger_side
    )
    if leverage:
        order.update_leverage(leverage)
    order.update_trigger_mode(trigger_with)
    if fallback and trigger_with == "limit":
        order.setup_fallback_action(**fallback)
    order.created_time = Runner.current_time
    if close_current_position:
        order.close_position = True
    Runner.positions[symbol][-1].add_order(order)

    return order


def order_if_percent_touched_amount(
    symbol,
    quantity,
    price_limit_percent,
    from_price=None,
    leverage=None,
    trigger_side=None,
    trigger_with="market",
    fallback=None,
):
    if from_price is None:
        current_price = last_price(symbol)
        price_limit = current_price + (current_price * price_limit_percent)
    else:
        price_limit = from_price + (from_price * price_limit_percent)

    order = order_if_touched_amount(
        symbol,
        quantity,
        price_limit,
        leverage=leverage,
        trigger_side=trigger_side,
        trigger_with=trigger_with,
        fallback=fallback,
    )
    return order


def cancel_order(symbol, id):
    Runner.loggers["main"].info("%s cancel order %i" % (symbol, id))
    client.futures_cancel_order(
        symbol=symbol, orderId=id, timestamp=Runner.current_time
    )
    return True


# def group_orders_in_trade(sells_raw, buys_raw):
#     sells = [sell for sell in sells_raw if sell["status"] != "CANCELED"]
#     buys = [buy for buy in buys_raw if buy["status"] != "CANCELED"]

#     sell_date = sells[0]["time"]
#     buy_date = buys[0]["time"]
#     n_sells = len(sells)
#     n_buys = len(buys)
#     sell_amount = sum([float(order["executedQty"]) for order in sells])
#     buy_amount = sum([float(order["executedQty"]) for order in buys])
#     avg_sell_price = (
#         sum([float(order["avgPrice"]) for order in sells]) / n_sells
#     )
#     avg_buy_price = sum([float(order["avgPrice"]) for order in buys]) / n_buys
#     pnl = (avg_sell_price * buy_amount) - (avg_buy_price * buy_amount)
#     return {
#         "sell_date": sell_date,
#         "sell_amount": sell_amount,
#         "avg_sell_price": avg_sell_price,
#         "buy_date": buy_date,
#         "buy_amount": buy_amount,
#         "avg_buy_price": avg_buy_price,
#         "pnl": pnl,
#     }


# def make_trades_from_orders(ords):
#     orders_sell = []
#     orders_buy = []
#     trade = None
#     for order in ords:
#         if order["side"] == "SELL":
#             if len(orders_buy) > 0:
#                 trade = group_orders_in_trade(orders_sell, orders_buy)
#                 yield trade
#                 orders_sell = []
#                 orders_buy = []
#             orders_sell.append(order)
#         if order["side"] == "BUY":
#             orders_buy.append(order)
#     if all([len(orders_buy) > 0, len(orders_sell) > 0]):
#         trade = group_orders_in_trade(orders_sell, orders_buy)
#         yield trade


# def historical_positions(symbol, limit=50):
#     orders = client.futures_get_all_orders(symbol="DOTUSDT", limit=limit)
#     orders.reverse()
#     orders_groups = []
#     long_position = get_open_position_api(symbol, "LONG")
#     short_position = get_open_position_api(symbol, "SHORT")
#     skip_dangling = True
#     for order in orders:
#         if long_position and skip_dangling:
#             print("last BUY order(s) are dangling")
#             if order["side"] == "BUY":
#                 pass
#         elif short_position and skip_dangling:
#             print("last SELL order(s) are dangling")
#             if order["side"] == "SELL":
#                 pass
#         else:
#             print("no dangling orders")
#             skip_dangling = False


"""

Setup SHORT for 0.5 DOTUSDT at price 26.419
symbol: DOTUSDT, side: SELL, amount 0.5
0.0
{'E': 1638801121249,
 'T': 1638801121244,
 'e': 'ORDER_TRADE_UPDATE',
 'o': {'L': '0',
       'R': False,
       'S': 'SELL',
       'T': 1638801121244,
       'X': 'NEW',
       'a': '0',
       'ap': '0',
       'b': '0',
       'c': 'cFITpGwiA0wgPYgFtlrC4s',
       'cp': False,
       'f': 'GTC',
       'i': 10442929808,
       'l': '0',
       'm': False,
       'o': 'MARKET',
       'ot': 'MARKET',
       'p': '0',
       'pP': False,
       'ps': 'BOTH',
       'q': '0.5',
       'rp': '0',
       's': 'DOTUSDT',
       'si': 0,
       'sp': '0',
       'ss': 0,
       't': 0,
       'wt': 'CONTRACT_PRICE',
       'x': 'NEW',
       'z': '0'}}
{'E': 1638801121249,
 'T': 1638801121244,
 'a': {'B': [{'a': 'USDT',
              'bc': '0',
              'cw': '852.22490181',
              'wb': '852.22490181'}],
       'P': [{'cr': '0.74979999',
              'ep': '26.4150',
              'iw': '0',
              'ma': 'USDT',
              'mt': 'cross',
              'pa': '-0.4',
              'ps': 'BOTH',
              's': 'DOTUSDT',
              'up': '0.00080000'}],
       'm': 'ORDER'},
 'e': 'ACCOUNT_UPDATE'}
{'E': 1638801121249,
 'T': 1638801121244,
 'e': 'ORDER_TRADE_UPDATE',
 'o': {'L': '26.415',
       'N': 'USDT',
       'R': False,
       'S': 'SELL',
       'T': 1638801121244,
       'X': 'PARTIALLY_FILLED',
       'a': '0',
       'ap': '26.4150',
       'b': '0',
       'c': 'cFITpGwiA0wgPYgFtlrC4s',
       'cp': False,
       'f': 'GTC',
       'i': 10442929808,
       'l': '0.4',
       'm': False,
       'n': '0.00422640',
       'o': 'MARKET',
       'ot': 'MARKET',
       'p': '0',
       'pP': False,
       'ps': 'BOTH',
       'q': '0.5',
       'rp': '0',
       's': 'DOTUSDT',
       'si': 0,
       'sp': '0',
       'ss': 0,
       't': 371720180,
       'wt': 'CONTRACT_PRICE',
       'x': 'TRADE',
       'z': '0.4'}}
{'E': 1638801121249,
 'T': 1638801121244,
 'a': {'B': [{'a': 'USDT',
              'bc': '0',
              'cw': '852.22384525',
              'wb': '852.22384525'}],
       'P': [{'cr': '0.74979999',
              'ep': '26.4148',
              'iw': '0',
              'ma': 'USDT',
              'mt': 'cross',
              'pa': '-0.5',
              'ps': 'BOTH',
              's': 'DOTUSDT',
              'up': '0.00090000'}],
       'm': 'ORDER'},
 'e': 'ACCOUNT_UPDATE'}
{'E': 1638801121249,
 'T': 1638801121244,
 'e': 'ORDER_TRADE_UPDATE',
 'o': {'L': '26.414',
       'N': 'USDT',
       'R': False,
       'S': 'SELL',
       'T': 1638801121244,
       'X': 'FILLED',
       'a': '0',
       'ap': '26.4148',
       'b': '0',
       'c': 'cFITpGwiA0wgPYgFtlrC4s',
       'cp': False,
       'f': 'GTC',
       'i': 10442929808,
       'l': '0.1',
       'm': False,
       'n': '0.00105656',
       'o': 'MARKET',
       'ot': 'MARKET',
       'p': '0',
       'pP': False,
       'ps': 'BOTH',
       'q': '0.5',
       'rp': '0',
       's': 'DOTUSDT',
       'si': 0,
       'sp': '0',
       'ss': 0,
       't': 371720181,
       'wt': 'CONTRACT_PRICE',
       'x': 'TRADE',
       'z': '0.5'}}
{'E': 1638801239559,
 'T': 1638801239553,
 'e': 'ORDER_TRADE_UPDATE',
 'o': {'L': '0',
       'R': True,
       'S': 'BUY',
       'T': 1638801239553,
       'X': 'NEW',
       'a': '0',
       'ap': '0',
       'b': '0',
       'c': 'ios_m01zt410TeL3ic3bIIOr',
       'cp': False,
       'f': 'GTC',
       'i': 10442988468,
       'l': '0',
       'm': False,
       'o': 'MARKET',
       'ot': 'MARKET',
       'p': '0',
       'pP': False,
       'ps': 'BOTH',
       'q': '0.5',
       'rp': '0',
       's': 'DOTUSDT',
       'si': 0,
       'sp': '0',
       'ss': 0,
       't': 0,
       'wt': 'CONTRACT_PRICE',
       'x': 'NEW',
       'z': '0'}}
{'E': 1638801239559,
 'T': 1638801239553,
 'a': {'B': [{'a': 'USDT',
              'bc': '0',
              'cw': '852.28949065',
              'wb': '852.28949065'}],
       'P': [{'cr': '0.82069999',
              'ep': '0.0000',
              'iw': '0',
              'ma': 'USDT',
              'mt': 'cross',
              'pa': '0',
              'ps': 'BOTH',
              's': 'DOTUSDT',
              'up': '0'}],
       'm': 'ORDER'},
 'e': 'ACCOUNT_UPDATE'}
{'E': 1638801239559,
 'T': 1638801239553,
 'e': 'ORDER_TRADE_UPDATE',
 'o': {'L': '26.273',
       'N': 'USDT',
       'R': True,
       'S': 'BUY',
       'T': 1638801239553,
       'X': 'FILLED',
       'a': '0',
       'ap': '26.2730',
       'b': '0',
       'c': 'ios_m01zt410TeL3ic3bIIOr',
       'cp': False,
       'f': 'GTC',
       'i': 10442988468,
       'l': '0.5',
       'm': False,
       'n': '0.00525460',
       'o': 'MARKET',
       'ot': 'MARKET',
       'p': '0',
       'pP': False,
       'ps': 'BOTH',
       'q': '0.5',
       'rp': '0.07090000',
       's': 'DOTUSDT',
       'si': 0,
       'sp': '0',
       'ss': 0,
       't': 371722036,
       'wt': 'CONTRACT_PRICE',
       'x': 'TRADE',
       'z': '0.5'}}

"""
