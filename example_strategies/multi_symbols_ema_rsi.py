import talib
from cryptrality.core import plot, plot_config
from cryptrality.misc import get_default_params

MARGIN_AMOUNT = 120
FUTURES_LEVERAGE = 2


BUY_VALUE = float(MARGIN_AMOUNT) * float(FUTURES_LEVERAGE)

TRADE_SYMBOLS = ["ETHUSDT", "BTCUSDT"]

CANDLE_PERIOD1 = "15m"
CANDLE_PERIOD2 = "1m"

MAX_DATA = 500

EMA_LONG = 40
EMA_SHORT = 10
RSI = 6


def initialize(state):
    plot_config(
        {
            "ema_long": {"plot": "root", "type": "line", "color": "black"},
            "ema_short": {"plot": "root", "type": "line", "color": "red"},
            "rsi": {"plot": "rsi", "type": "line", "color": "black"},
            "oversold": {"plot": "rsi", "type": "line", "color": "red"},
            "overbought": {"plot": "rsi", "type": "line", "color": "red"},
        }
    )
    state.params = {}
    state.balance_quoted = 0
    state.ema_values = {}
    state.params["DEFAULT"] = {
        "ema_long": EMA_LONG,
        "ema_short": EMA_SHORT,
        "rsi": RSI,
    }


@schedule(interval=CANDLE_PERIOD1, symbols=TRADE_SYMBOLS, window_size=MAX_DATA)
def ema_5m(state, dataMap):
    for symbol, data in dataMap.items():
        strategy_logic_5m(state, data, symbol)


def strategy_logic_5m(state, data, symbol):

    if data is None:
        return

    params = get_default_params(state, symbol)
    ema_long_period = params["ema_long"]
    ema_short_period = params["ema_short"]
    ema_long = talib.EMA(data["close"], timeperiod=ema_long_period)
    ema_short = talib.EMA(data["close"], timeperiod=ema_short_period)
    state.ema_values[symbol] = [ema_long[-1], ema_short[-1]]


@schedule(interval=CANDLE_PERIOD2, symbols=TRADE_SYMBOLS, window_size=MAX_DATA)
def rsi_1m(state, dataMap):
    for symbol, data in dataMap.items():
        strategy_logic_rsi_1m(state, data, symbol)


def strategy_logic_rsi_1m(state, data, symbol):
    if data is None:
        return

    params = get_default_params(state, symbol)
    try:
        ema_long, ema_short = state.ema_values[symbol]
    except KeyError:
        ema_long, ema_short = [None, None]
    rsi_period = params["rsi"]
    rsi = talib.RSI(data["close"], timeperiod=rsi_period)
    data_plot = {key: values[-1] for key, values in data.items()}
    data_plot["rsi"] = rsi[-1]
    data_plot["ema_long"] = ema_long
    data_plot["ema_short"] = ema_short
    data_plot["oversold"] = 10
    data_plot["overbought"] = 70

    if len(data["close"]) < rsi_period * 2:
        return

    position = get_open_position(symbol, side="LONG")
    has_position = position is not None
    buy = False
    sell = False
    if has_position:
        sell_quantity = position.quantity
    if (
        ema_long
        and not has_position
        and ema_long <= ema_short
        and rsi[-1] < 10
    ):
        buy = True
    elif ema_long and has_position and ema_long <= ema_short and rsi[-1] >= 70:
        sell = True
    if buy:
        order_market_value(symbol, value=BUY_VALUE, leverage=FUTURES_LEVERAGE)
        logger.info("buy %s %s" % (symbol, data["close"][-1]))
    elif sell:
        order_market_amount(
            symbol, quantity=-1 * sell_quantity, leverage=FUTURES_LEVERAGE
        )
        logger.info("sell %s %s" % (symbol, data["close"][-1]))
    plot(symbol, data_plot)
