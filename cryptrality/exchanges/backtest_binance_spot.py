import os
import random
from datetime import datetime
from binance.helpers import round_step_size
from binance.client import Client
from cryptrality.misc import (
    round_time,
    str_to_minutes,
    xopen,
    candle_close_timestamp,
)
from cryptrality.core import (
    State,
    RunnerClass,
    OrderSide,
    OrderType,
    OrderStatus,
    Order,
    Position,
)
from cryptrality.__config__ import Config
from numpy import ndarray, array, append
from copy import deepcopy
import cryptrality.exchanges.binance_common as bc
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

config = Config()

CACHED_KLINES_PATH = config.CACHED_KLINES_PATH


client = Client()


SLIPPAGE = config.SLIPPAGE
FEES = config.FEES


def load_klines_from_file(file_name: str) -> Iterator[List[str]]:
    """
    Read the historical data from a csv file, return a list of each
    line in the csv split as a list (a list of list)
    """
    with xopen(file_name, "rt") as kline_in:
        for kline in kline_in:
            yield kline.strip().split(",")


def klines_translate(
    data: Iterator[Any], symbol: str, period_str: str
) -> Iterator[Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]]]:
    for candle in data:
        yield bc.list_to_klines(candle, symbol, period_str)


def write_klines_to_file(klines_data, file_name):
    """
    Write the kline data -eg retrieved from an API call- to a csv file
    """
    with xopen(file_name, "wt") as kline_out:
        for kline in klines_data:
            kline_out.write("%s\n" % ",".join(map(str, kline)))


class Runner(RunnerClass):
    """
    A class that coordinate the websocket stream, store, check anv validate ochl data
    and various information and synchronize the execution of the strategy handlers
    """

    def setup_data(
        self,
        schedule: List[Dict[str, Union[str, Callable, List[str], int]]],
        start: str,
        end: str,
        state: State,
    ) -> None:
        """
        Read the schedule decorator from the strategy code and initialize the
        connection with the websocket, subscribing to the requested channels,
        and setup the execution schedule for each handlers
        """
        self.state = state
        self.schedule = []
        self.next_execution = {"timestamp": None, "intervals": []}
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
        self.get_candles(start, end)

    def get_candles(self, start: str, end: str) -> None:
        """
        Look in the cache folder if a name-matching file exists,
        request the historical data with an API call.
        Return a generator that merge all requested symbols and periods
        sorted by closing time, and return them ad binance the kline stream
        websocket format
        """
        historical_data = {}

        for period_info in self.schedule:
            period = period_info["interval"]
            historical_data[period] = {}
            for symbol in period_info["symbols"]:
                klines_data_name = os.path.join(
                    CACHED_KLINES_PATH,
                    "%s.csv.gz"
                    % "_".join(
                        [
                            "binance_spot",
                            symbol,
                            period,
                            start.replace("-", "_"),
                            end.replace("-", "_"),
                        ]
                    ),
                )
                if not os.path.exists(CACHED_KLINES_PATH):
                    os.makedirs(CACHED_KLINES_PATH)
                if os.path.exists(klines_data_name) and os.path.isfile(
                    klines_data_name
                ):
                    start_data = load_klines_from_file(klines_data_name)
                else:
                    min_period = str_to_minutes(period)
                    date_object1 = datetime.strptime(start, "%d-%m-%y")
                    date_object2 = datetime.strptime(end, "%d-%m-%y")
                    from_time = round_time(
                        date_object1, round_to=60 * min_period
                    )
                    to_time = round_time(
                        date_object2, round_to=60 * min_period
                    )
                    ts = int(from_time.timestamp()) * 1000
                    ts2 = int(to_time.timestamp()) * 1000
                    Runner.loggers["main"].info(
                        "Caching %s klines for %s" % (period, symbol)
                    )
                    start_data = client.get_historical_klines(
                        symbol, period, start_str=ts, end_str=ts2
                    )
                    write_klines_to_file(start_data, klines_data_name)
                historical_data[period][symbol] = klines_translate(
                    start_data, symbol, period
                )
        self.klines = sync_klines(historical_data)

    @staticmethod
    def user_data_handler(
        k: Dict[
            str,
            Union[
                str,
                int,
                Dict[str, Union[str, int]],
                Dict[str, Union[str, int, bool]],
                Dict[str, Union[str, List[Dict[str, str]]]],
            ],
        ]
    ) -> None:
        """
        Handlers for the user streams, it receive and parse position information, orders
        status information and configuration information (eg leverage changes)
        Depending on the message it will add or close position object in the symbol position
        list, update and react to order filling status update.
        """
        message_type = k["e"]

        if message_type == "ACCOUNT_UPDATE":
            # Position info here
            try:
                positions_info = k["a"]["P"]
            except KeyError:
                pass
            if len(positions_info) > 0:
                position = positions_info[0]
                symbol = position["s"]
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
            order_id = k["o"]["i"]
            symbol = k["o"]["s"]
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
                Runner.positions[symbol].append(last_position)

            orders_ids = [o.id for o in last_position.orders]
            try:
                updated_order = orders_ids.index(order_id)
            except ValueError:
                updated_order = None

            if updated_order is None:
                Runner.loggers["main"].warning(
                    "Order %i is not recorder " "in the system" % order_id
                )
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
                ].executed_quantity = filled_quantity
                last_position.orders[
                    updated_order
                ].executed_price = order_price
                last_position.orders[updated_order].fees = (
                    filled_quantity * order_price * FEES
                )
                if new_status == OrderStatus.Filled:
                    if last_position.orders[updated_order].close_position:
                        realized_profit = float(k["o"]["rp"])
                        last_position.exit_price = order_price
                        last_position.exit_time = Runner.current_time
                        last_position.pnl = realized_profit
        elif message_type == "ACCOUNT_CONFIG_UPDATE":
            # leverage info here
            try:
                event_time = datetime.fromtimestamp(Runner.current_time / 1000)
                update_leverage = k["ac"]["l"]
                symbol = k["ac"]["s"]
                # Runner.loggers["main"].info(
                #     "%s Update leverage to %iX for symbol %s"
                #     % (event_time, update_leverage, symbol)
                # )
            except KeyError:
                pass

    def candle_data_handler(
        self, candle: Dict[str, Union[str, int, bool]]
    ) -> None:
        """
        Check for orders limits at every update.
        This handles if_touched orders, where the limit is specified in the order
        object, if the limit is breached in the specified direction a market (or limit)
        order is sent to the exchange.

        This handler will also check for limit expiration (eg set the limit expires
        after 10 second than need to be cancelled, and eventually filled with a market
        order)
        """
        current_symbol = candle["s"]
        candle_open = datetime.utcfromtimestamp(candle["t"] / 1000)
        Runner.current_price[current_symbol] = float(candle["c"])

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

        for i in range(len(last_position.orders)):
            order = last_position.orders[i]
            if order.type in types_to_monitor:
                if order.status not in status_to_monitor:
                    continue
                order_time = datetime.utcfromtimestamp(
                    order.created_time / 1000
                )
                if order_time > candle_open:
                    continue
                quantity = order.quantity
                trigger_side = order.trigger_side
                close_current_position = order.close_position
                check_iftouched = False
                if trigger_side and order.type == OrderType.IfTouched:
                    if trigger_side == 1:
                        if float(candle["h"]) >= order.limit_price:
                            check_iftouched = True
                    elif trigger_side == -1:
                        if float(candle["l"]) <= order.limit_price:
                            check_iftouched = True
                else:
                    if order.type == OrderType.Limit:
                        if trigger_side == 1:
                            if float(candle["h"]) >= order.limit_price:
                                order_new, order_filled = order_trade_update(
                                    current_symbol,
                                    abs(quantity),
                                    "SELL",
                                    order.limit_price,
                                    order.created_time,
                                    close_current_position,
                                )
                                order_filled["o"]["i"] = order.id
                                if close_current_position:
                                    position_new = account_update(
                                        current_symbol, 0, 0
                                    )
                                else:
                                    position_new = account_update(
                                        current_symbol,
                                        quantity,
                                        order.limit_price,
                                    )
                                Runner.messages += [order_filled, position_new]
                        elif trigger_side == -1:
                            if float(candle["l"]) <= order.limit_price:
                                order_new, order_filled = order_trade_update(
                                    current_symbol,
                                    abs(quantity),
                                    "BUY",
                                    order.limit_price,
                                    order.created_time,
                                    close_current_position,
                                )
                                order_filled.id = order.id
                                if close_current_position:
                                    position_new = account_update(
                                        current_symbol, 0, 0
                                    )
                                else:
                                    position_new = account_update(
                                        current_symbol,
                                        quantity,
                                        order.limit_price,
                                    )
                                Runner.messages += [order_filled, position_new]

                if check_iftouched and order.side == OrderSide.Buy:
                    side_str = "BUY"
                    order_new, order_filled = order_trade_update(
                        current_symbol,
                        abs(quantity),
                        side_str,
                        order.limit_price,
                        candle["t"],
                        close_current_position,
                    )
                    last_position.orders[i].id = order_new["o"]["i"]
                    if close_current_position:
                        position_new = account_update(current_symbol, 0, 0)
                    else:
                        position_new = account_update(
                            current_symbol, quantity, order.limit_price
                        )
                    Runner.messages += [order_new, position_new, order_filled]
                    while len(Runner.messages) > 0:
                        msg = Runner.messages.pop(0)
                        self.msg_handler(msg)
                elif check_iftouched and order.side == OrderSide.Sell:
                    side_str = "SELL"
                    order_new, order_filled = order_trade_update(
                        current_symbol,
                        abs(quantity),
                        side_str,
                        order.limit_price,
                        candle["t"],
                        close_current_position,
                    )
                    last_position.orders[i].id = order_new["o"]["i"]
                    if close_current_position:
                        position_new = account_update(current_symbol, 0, 0)
                    else:
                        position_new = account_update(
                            current_symbol, quantity, order.limit_price
                        )
                    Runner.messages += [order_new, position_new, order_filled]
                    while len(Runner.messages) > 0:
                        msg = Runner.messages.pop(0)
                        self.msg_handler(msg)

    def msg_handler(
        self,
        k: Dict[
            str,
            Union[
                str,
                int,
                Dict[str, Union[str, int]],
                Dict[str, Union[str, int, bool]],
                Dict[str, Union[str, List[Dict[str, str]]]],
            ],
        ],
    ) -> None:
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
            message_type = k["e"]
        except KeyError:
            message_type = None
        # Receive Positions/Orders/Config update here
        # Interact with object in the singleton
        # Maybe convert to a dedicated DB later one
        if message_type is None:
            Runner.loggers["main"].warning(k)
            return
        elif message_type == "kline":
            candle = k["k"]
            current_interval = candle["i"]
            current_symbol = candle["s"]
            # Candle handling starts here
            self.candle_data_handler(candle)
            # prepare ochl data to pass to the handler functions
            if candle["x"]:
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
                                try:
                                    Runner.historical_klines[current_interval][
                                        current_symbol
                                    ] = self.update_ochl(
                                        {}, candle, schedule["window_size"]
                                    )
                                except KeyError:
                                    Runner.historical_klines[
                                        current_interval
                                    ] = {}
                                    Runner.historical_klines[current_interval][
                                        current_symbol
                                    ] = self.update_ochl(
                                        {}, candle, schedule["window_size"]
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
                                    data_map[
                                        symbol
                                    ] = Runner.historical_klines[
                                        schedule["interval"]
                                    ][
                                        symbol
                                    ]
                                except KeyError:
                                    data_map[symbol] = None
                            schedule["fn"](self.state, data_map)
                            # Runner.loggers["exec"].info(
                            #     "Exec function %s for interval %s "
                            #     "with symbols %s"
                            #     % (
                            #         schedule["fn"].__name__,
                            #         schedule["interval"],
                            #         schedule["symbols"],
                            #     )
                            # )

                    self.update_executions(candle_close_time)
        else:
            self.user_data_handler(k)

    @staticmethod
    def update_ochl(
        historical_klines: Dict[str, ndarray],
        candle: Dict[str, Union[str, int, bool]],
        max_len: int,
    ) -> Dict[str, ndarray]:
        """
        Update the candlestick data ad every new closed candle.
        Check for duplicated candles and for missing data in the dataset.
        In case of duplicate it removes the first entry (keep the last one)
        and in case of missing data it re-init the ochl data with an additional
        API call
        """
        kline_dict = {
            "timestamp": "t",
            "open": "o",
            "close": "c",
            "high": "h",
            "low": "l",
            "buy_volume": "Q",
            "volume": "v",
        }
        for key, value in kline_dict.items():
            try:
                historical_klines[key] = append(
                    historical_klines[key], float(candle[value])
                )
                historical_klines[key] = historical_klines[key][-max_len:]
            except KeyError:
                historical_klines[key] = array(
                    [float(candle[value])], dtype=float
                )
        return historical_klines

    def run_forever(self) -> None:
        """
        Loop over all the messages
        """
        for k in self.klines:
            while len(Runner.messages) > 0:
                msg = Runner.messages.pop(0)
                self.msg_handler(msg)
            if k["E"]:
                Runner.current_time = k["E"]
            self.msg_handler(k)
            """
            Simulate websocket messages in binance
            """
            while len(Runner.messages) > 0:
                msg = Runner.messages.pop(0)
                self.msg_handler(msg)


def config_update(
    symbol: str, leverage: int, timestamp: int
) -> Dict[str, Union[str, int, Dict[str, Union[str, int]]]]:
    """
    Return a small dic, emulating leverage update messages
    from the user websocket
    """
    config = {
        "e": "ACCOUNT_CONFIG_UPDATE",
        "E": timestamp,
        "T": timestamp,
        "ac": {"s": symbol, "l": leverage},
    }
    return config


def account_update(
    symbol: str, quantity: float, price: float
) -> Dict[str, Union[str, int, Dict[str, Union[str, List[Dict[str, str]]]]]]:
    """
    Return a dic emulating an open position update message
    as in the user websocket stream
    """
    try:
        timestamp = Runner.current_time
    except KeyError:
        # API call to get last price here
        pass
    position = {
        "e": "ACCOUNT_UPDATE",
        "E": timestamp,
        "T": timestamp,
        "a": {
            "m": "ORDER",
            "B": [
                {
                    "a": "USDT",
                    "wb": "122624.12345678",
                    "cw": "100.12345678",
                    "bc": "50.12345678",
                },
            ],
            "P": [
                {
                    "s": symbol,
                    "pa": str(quantity),
                    "ep": str(price),
                    "cr": "200",
                    "up": "0",
                    "mt": "isolated",
                    "iw": "0.00000000",
                    "ps": "BOTH",
                }
            ],
        },
    }
    return position


def order_trade_update_msg(
    symbol: str,
    quantity: float,
    side: str,
    price: float,
    timestamp: int,
    status: str,
    order: Optional[
        Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]]
    ] = None,
    closing: bool = False,
) -> Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]]:
    """
    Return a dic emulating an order message as in the user websocket stream.
    """
    if order is None:
        order = {}
    if status == "NEW":
        id = int("".join(map(str, random.sample(range(10), 10))))
        order = {
            "e": "ORDER_TRADE_UPDATE",
            "T": timestamp,
            "E": timestamp,
            "o": {
                "s": symbol,
                "c": "123abcXYZabc321XYZ",
                "S": side,
                "o": "MARKET",
                "f": "GTC",
                "q": str(quantity),
                "p": "0",
                "ap": "0",
                "sp": "0",
                "x": "NEW",
                "X": "NEW",
                "i": id,
                "l": "0",
                "z": "0",
                "L": "0",
                "T": timestamp,
                "t": 0,
                "b": "0",
                "a": "0",
                "m": False,
                "R": False,
                "wt": "CONTRACT_PRICE",
                "ot": "MARKET",
                "ps": "BOTH",
                "rp": "0",
                "cp": False,
            },
        }
    elif status == "FILLED":
        order["o"]["l"] = str(quantity)
        order["o"]["L"] = str(price)
        order["o"]["z"] = str(quantity)
        order["o"]["ap"] = str(price)
        order["o"]["X"] = status
        if closing:
            position = Runner.positions[symbol][-1]
            open_amount = abs(position.quantity) * position.price
            close_amount = abs(position.quantity) * price
            if position.quantity < 0:
                realized_profit = (
                    open_amount
                    - close_amount
                    - (open_amount * FEES)
                    - (close_amount * FEES)
                )
            else:
                realized_profit = (
                    close_amount
                    - open_amount
                    - (open_amount * FEES)
                    - (close_amount * FEES)
                )
            order["o"]["rp"] = str(realized_profit)
    return order


def order_trade_update(
    symbol: str,
    quantity: float,
    side: str,
    price: float,
    timestamp: int,
    closing: bool = False,
) -> Tuple[
    Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]],
    Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]],
]:
    """
    Convenience function that create orders update both NEW and FILLED messages
    """
    order_new = order_trade_update_msg(
        symbol, quantity, side, price, timestamp, "NEW"
    )
    order_filled = order_trade_update_msg(
        symbol,
        quantity,
        side,
        price,
        timestamp,
        "FILLED",
        deepcopy(order_new),
        closing,
    )
    return (order_new, order_filled)


def sync_klines(
    klines_periods: Dict[str, Dict[str, Iterator[Any]]]
) -> Iterator[Dict[str, Union[int, str, Dict[str, Union[str, int, bool]]]]]:
    """
    Generator that synchronize the klines list by closing time
    """
    last_timestamp = 0
    buffer_klines = {}
    buffer_keys = []
    for symbol in klines_periods:
        for period in klines_periods[symbol]:
            if last_timestamp == 0:
                buffer_key = "%s_%s" % (symbol, period)
                buffer_keys.append(buffer_key)
                buffer_klines[buffer_key] = next(
                    klines_periods[symbol][period]
                )

    last_timestamp = min(
        [
            datetime.utcfromtimestamp(buffer_klines[k]["E"] / 1000)
            for k in buffer_keys
        ]
    )
    run_forever = True
    run = 0
    while run_forever:
        for symbol in klines_periods:
            for period in klines_periods[symbol]:
                buffer_key = "%s_%s" % (symbol, period)
                if buffer_key in buffer_keys:
                    if (
                        datetime.utcfromtimestamp(
                            buffer_klines[buffer_key]["E"] / 1000
                        )
                        == last_timestamp
                    ):
                        yield (buffer_klines[buffer_key])
                        run += 1
                        try:
                            buffer_klines[buffer_key] = next(
                                klines_periods[symbol][period]
                            )
                        except StopIteration:
                            buffer_keys.remove(buffer_key)
        if len(buffer_keys) > 0:
            last_timestamp = min(
                [
                    datetime.utcfromtimestamp(buffer_klines[k]["E"] / 1000)
                    for k in buffer_keys
                ]
            )
        else:
            run_forever = False


def get_index_from_data(candles_list, i=4):
    for candle in candles_list:
        yield float(candle[i])


def get_open_position(symbol: str, side: str) -> Optional[Position]:
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
        pass
    return open_position


def last_price(symbol):
    """
    use the price from the latest websocket update (
    it doesn't call the API for the last price)
    """
    try:
        return Runner.current_price[symbol]
    except KeyError:
        return None


def order_market_amount(
    symbol: str, quantity: float, leverage: Optional[int] = None
) -> Order:
    """
    Perform a market order for a given quantity at the specified
    leverage. the quantity is intended as base asset quantity
    if the quantity is negative the order will be a sell order
    if positive a buy order
    """
    if leverage:
        config = config_update(symbol, leverage, Runner.current_time)
        Runner.messages.append(config)
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
    elif quantity <= 0:
        order_side = 1
        side_str = "SELL"
    order_new, order_filled = order_trade_update(
        symbol,
        abs(quantity),
        side_str,
        Runner.current_price[symbol],
        Runner.current_time,
        close_current_position,
    )
    if close_current_position:
        position_new = account_update(symbol, 0, 0)
    else:
        position_new = account_update(
            symbol, quantity, Runner.current_price[symbol]
        )
    Runner.messages += [order_new, position_new, order_filled]
    order = Order(order_new["o"]["i"], symbol, 0, order_side, quantity)
    order.created_time = Runner.current_time
    if close_current_position:
        order.close_position = True
    Runner.positions[symbol][-1].add_order(order)

    return order


def order_limit_amount(symbol, quantity, price, leverage=None, fallback=None):
    """
    Perform a limit order for a given quantity at the specified
    leverage. the quantity is intended as base asset quantity
    if the quantity is negative the order will be a sell order
    if positive a buy order
    """
    if leverage:
        config = config_update(symbol, leverage, Runner.current_time)
        Runner.messages.append(config)
    try:
        price_precision = Runner.price_precision[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_spot(client, symbol)
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
    stepped_price = round_step_size(price, price_precision)

    if quantity > 0:
        order_side = 0
        side_str = "BUY"
    elif quantity <= 0:
        order_side = 1
        side_str = "SELL"
    order_new, order_filled = order_trade_update(
        symbol,
        abs(quantity),
        side_str,
        stepped_price,
        Runner.current_time,
        close_current_position,
    )
    Runner.messages += [order_new]
    order = Order(
        order_new["o"]["i"], symbol, 1, order_side, quantity, stepped_price
    )
    order.created_time = Runner.current_time
    if close_current_position:
        order.close_position = True
    Runner.positions[symbol][-1].add_order(order)
    Runner.messages += [order_new]
    return order


def order_market_value(
    symbol: str, value: int, leverage: Optional[int] = None
) -> Order:
    """
    Perform a market order for a given value at the specified
    leverage. the value is intended as quoted asset amount.
    If the value is negative the order will be a sell order
    if positive a buy order
    """
    try:
        step_size = Runner.step_size[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_spot(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision
    try:
        current_price = Runner.current_price[symbol]
    except KeyError:
        # API call to get last price here
        pass
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
        step_size, price_precision = bc.get_step_size_spot(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision

    stepped_price = round_step_size(price, price_precision)
    quantity = round_step_size(value / stepped_price, step_size)
    order = order_limit_amount(symbol, quantity, stepped_price, leverage)
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

    try:
        price_precision = Runner.price_precision[symbol]
    except KeyError:
        step_size, price_precision = bc.get_step_size_spot(client, symbol)
        Runner.step_size[symbol] = step_size
        Runner.price_precision[symbol] = price_precision

    price_limit = round_step_size(price_limit, price_precision)

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
    order = Order(
        None, symbol, 2, order_side, quantity, price_limit, 1, trigger_side
    )
    if leverage:
        order.update_leverage(leverage)
    order.update_trigger_mode(trigger_with)
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
):
    if from_price is None:
        current_price = Runner.current_price[symbol]
        price_limit = current_price + (current_price * price_limit_percent)
    else:
        price_limit = from_price + (from_price * price_limit_percent)

    order = order_if_touched_amount(
        symbol, quantity, price_limit, leverage, trigger_side
    )
    return order


def cancel_order(symbol, id):
    try:
        last_position = Runner.positions[symbol][-1]
    except KeyError:
        Runner.positions[symbol] = []
        last_position = None
    except IndexError:
        last_position = None
    if last_position is None or last_position.is_closed:
        Runner.loggers["main"].error(
            "There are no orders or positions yet for %s" % symbol
        )
        return

    orders_ids = [o.id for o in last_position.orders]
    try:
        cancel_idx = orders_ids.index(id)
    except ValueError:
        cancel_idx = None
    if cancel_idx:
        Runner.loggers["main"].info("cancel order %i" % cancel_idx)
        last_position.orders[cancel_idx].cancel()
        cancelled_order = last_position.orders[cancel_idx]
        if cancelled_order.type == OrderType.Limit:
            # cancel the order also in the exchange
            pass
        print(last_position.orders[cancel_idx].status)
