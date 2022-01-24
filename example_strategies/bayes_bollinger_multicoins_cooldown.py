##+------------------------------------------------------------------+
##| BAYESIAN BBANDS | 15m                                             |
##+------------------------------------------------------------------+

import talib
from cryptrality.core import plot, plot_config
#from simplebot.exchanges.backtest_binance_futures import *

STRATEGY_NAME="Bayesian Bollinger strategy"


SYMBOLS =  ["VITEUSDT", "MATICUSDT", "LUNAUSDT", "MANAUSDT", "ZILUSDT", "NKNUSDT"]

#SYMBOLS = ['ETHUSDT', 'BTCUSDT']
INTERVAL = "15m"

MARGIN_AMOUNT = 100

FUTURES_LEVERAGE =  2

## Use the actual buy amount after leverage

FIX_BUY_AMOUNT = MARGIN_AMOUNT * FUTURES_LEVERAGE

##+------------------------------------------------------------------+
##| SELL Options                                                     |
##+------------------------------------------------------------------+

ATR_TAKE_PROFIT = 6	            # A multiplier on the ATR value (e.g. 4)
ATR_STOP_LOSS = 6               # A multiplier on the ATR value (e.g. 6)
COLLECT_DATA = False            # if True a python dictionary with the trade data
                                # is printed at the end of each day
SIGNALS = [1, 4, 5]             # Signal to include, possible number 1, 2, 3, 4, 5
                                # Suggested values [1, 5]. For high volatile symbols [1, 3, 4, 5]


import numpy as np
from numpy import greater, less, sum, nan_to_num, exp
from datetime import datetime


##+------------------------------------------------------------------+
##| Settings in state (could set different tp/sl for each symbol)    |
##+------------------------------------------------------------------+


def initialize(state):
    plot_config({
        'bbands_high': {
            'plot': 'root',
            'type': 'area',
            'color': None,
            'upper': 'bbands_high',
            'lower': 'bbands_low'           
        },
        'kbands_high': {
            'plot': 'root',
            'type': 'area',
            'color': None,
            'upper': 'kbands_high',
            'lower': 'kbands_low'           
        },
        'stop_loss': {
            'plot': 'root',
            'type': 'line',
            'color': 'red'
        },
        'take_profit': {
            'plot': 'root',
            'type': 'line',
            'color': 'green'
        },
        'bbands_mid': {
            'plot': 'root',
            'type': 'line',
            'color': 'black'
        },
        'kbands_mid': {
            'plot': 'root',
            'type': 'line',
            'color': 'red'
        },
        'prob_prime': {
            'plot': 'bbands',
            'type': 'line',
            'color': 'black'
        },
        'sigma_up': {
            'plot': 'bbands',
            'type': 'line',
            'color': 'green'
        },
        'sigma_down': {
            'plot': 'bbands',
            'type': 'line',
            'color': 'red'
        }
    })
    state.number_offset_trades = 0
    state.zero_signal_timer = {}
    state.params = {}
    state.past_daily_candles = {}
    state.hourly_candles = {}
    state.cooldown = {}
    state.balance_quoted = 0
    state.collect_data = None
    state.params["DEFAULT"] = {
        "bolligner_period": 20,
        "bolligner_sd": 2,
        "keltner_ema": 20,
        "keltner_atr": 20,
        "keltner_n": 2,
        "ema_longer_period": 50,
        "ema_long_period": 40,
        "ema_short_period": 10,
        "atr_stop_loss": ATR_STOP_LOSS,
        "atr_take_profit": ATR_TAKE_PROFIT,
        "max_loss_percent": None,
        "lower_threshold": 15,
        "bayes_period": 20,
        "keltner_filter": True,
        "ema_filter": True,
        "keep_signal": 10,
        "use_cooldown": True,
        "max_candels_with_0_signals": 24,
        "signals_mode": SIGNALS,
        "collect_data": COLLECT_DATA}


@schedule(interval=INTERVAL, symbols=SYMBOLS, window_size=200)
def handler1(state, data):
    #portfolio = query_portfolio()
    ## Balance query is not implemented yet
    balance_quoted = 1000
    state.balance_quoted = float(balance_quoted)

    buy_value = FIX_BUY_AMOUNT
    for this_symbol in data.keys():
        handler_main(
            state, data[this_symbol], buy_value, this_symbol)

#### Waiting Functions


def signal_no_wait(position_manager, trade_data, indicators_data):  
    position_manager.stop_waiting()
    return True


def signal_buy_cooldown(position_manager, trade_data, indicators_data):
    signal = False
    cooldown = indicators_data["cooldown"]
    if cooldown == False:
        position_manager.stop_waiting()
        signal = True
    return signal

def signal_sell_cci(position_manager, trade_data, indicators_data):
    signal = False
    adx = indicators_data["adx"]["data"]
    cci = indicators_data["cci"]["data"]
    if (adx[-1] < 25 or cci[-1] < 80) or cci[-1] > 250:
        signal = True
        position_manager.stop_waiting()
    return signal

####

def handler_main(state, data, amount, symbol):
    if data is None:
        return
    if len(data["close"]) < 50:
        return

    symbol = symbol

    if symbol == "BNBUSDT":
        refill_bnb(state, data, 20, symbol)
        return

    #--------------------------------------------#
    # Get Parameters and init variables in state #
    #--------------------------------------------#

    params = get_default_params(state, symbol)
    atr_stop_loss = params["atr_stop_loss"]
    atr_take_profit = params["atr_take_profit"]
    collect_data = params["collect_data"]
    bolligner_period = params["bolligner_period"]
    bolligner_sd = params["bolligner_sd"]
    keltner_ema = params["keltner_ema"]
    keltner_atr = params["keltner_atr"]
    keltner_n = params["keltner_n"]

    ema_longer_period = params["ema_longer_period"]
    ema_long_period = params["ema_long_period"]
    ema_short_period = params["ema_short_period"]

    lower_threshold = params["lower_threshold"]
    bayes_period =  params["bayes_period"]
    signals_mode =  params["signals_mode"]
    max_candels_with_0_signals = params["max_candels_with_0_signals"]
    max_loss_percent = params["max_loss_percent"]

    keltner_filter = params["keltner_filter"]
    ema_filter = params["ema_filter"]
    keep_signal = params["keep_signal"]
    use_cooldown = params["use_cooldown"]
    lift_sl = True

    try:
        zero_signal_timer = state.zero_signal_timer[symbol]
    except KeyError:
        state.zero_signal_timer[symbol] = 0
        zero_signal_timer = state.zero_signal_timer[symbol]

    try:
        past_daily_candles = state.past_daily_candles[symbol]
    except KeyError:
        state.past_daily_candles[symbol] = {
            "yesterday": None, "2yesterday": None}
        past_daily_candles = state.past_daily_candles[symbol]

    try:
        hourly_candles = state.hourly_candles[symbol]
    except KeyError:
        state.hourly_candles[symbol] = []
        hourly_candles = state.hourly_candles[symbol]

    try:
        cooldown = state.cooldown[symbol]
    except KeyError:
        state.cooldown[symbol] = False
        cooldown = state.cooldown[symbol]
    last_cooldown = cooldown

    #------------#
    # Indicators #
    #------------#


    cci_data = talib.CCI(
        data['high'], data['low'], data['close'],
        timeperiod=20)
    adx_data = talib.ADX(
        data['high'], data['low'], data['close'],
        timeperiod=14)
    atr_data = talib.ATR(
        data['high'], data['low'], data['close'],
        timeperiod=12)
    atr = atr_data[-1]
    #engulfing = data.cdl#().last

    data_plot = {
        key: values[-1] for key, values in data.items()}
    data_plot['stop_loss'] = None
    data_plot['take_profit'] = None
    data_plot['prob_prime'] = None
    data_plot['sigma_up'] = None
    data_plot['sigma_down'] = None
    


    ema_long_data = talib.EMA(
        data["close"], ema_long_period)
    ema_short_data = talib.EMA(
        data["close"], ema_short_period)
    ema_long = ema_long_data[-1]
    ema_short = ema_short_data[-1]

    yesterday_candle = past_daily_candles["yesterday"]
    before_yesterday_candle = past_daily_candles["2yesterday"]

    if yesterday_candle is None:
        past_daily_candles["yesterday"] = get_yesterday_daily_candle(data)
        state.past_daily_candles[symbol] = past_daily_candles
        yesterday_candle = past_daily_candles["yesterday"]

    if int(datetime.fromtimestamp(data["timestamp"][-1] / 1000).minute) == 0:
            if int(datetime.fromtimestamp(data["timestamp"][-1] / 1000).hour) == 0:
                past_daily_candles["2yesterday"] = past_daily_candles["yesterday"]
                past_daily_candles["yesterday"] = get_yesterday_daily_candle(data)
                state.past_daily_candles[symbol] = past_daily_candles

    yesterday_levels = compute_daily_levels(yesterday_candle)
    if yesterday_levels:
        r1 = yesterday_levels["resistance1"]
        s1 = yesterday_levels["support1"]
        pivot = yesterday_levels["pivot"]
    else:
        r1 = None
        s1 = None
        pivot = None

    if before_yesterday_candle:
        before_yesterday_levels = compute_daily_levels(before_yesterday_candle)
        past_r1 = before_yesterday_levels["resistance1"]
    else:
        past_r1 = None

    take_last = 70
    max_1h_candles = 500

    bbands = talib.BBANDS(
        data["close"],
        timeperiod=bolligner_period,
        nbdevup=bolligner_sd, nbdevdn=bolligner_sd)

    kbands = keltner_channels(
        data, keltner_ema, keltner_atr, keltner_n, take_last)

    data_plot['bbands_high'] = bbands[0][-1]
    data_plot['bbands_mid'] = bbands[1][-1]
    data_plot['bbands_low'] = bbands[2][-1]
    data_plot['kbands_high'] = kbands["high"][-1]
    data_plot['kbands_mid'] = kbands["middle"][-1]
    data_plot['kbands_low'] = kbands["low"][-1]

    current_price = data["close"][-1]
    current_low = data["low"][-1]
    mid_low_point = 0.995 * (
        bbands[1][-1] + bbands[2][-1]) / 2

    if len(hourly_candles) == 0:
        
        new_hourly_candles = list(
            get_1h_candles(
                data['timestamp'], data["open"], data["close"],
                data["high"], data["low"], data["volume"])
        )
    else:
        new_hourly_candles = list(
            get_1h_candles(
                data['timestamp'][-4:], data["open"][-4:],
                data["close"][-4:], data["high"][-4:],
                data["low"][-4:], data["volume"][-4:])
        )
    if len(new_hourly_candles) > 0:
        hourly_candles += new_hourly_candles

    if len(hourly_candles) > max_1h_candles:
        hourly_candles = hourly_candles[-max_1h_candles:]
    state.hourly_candles[symbol] = hourly_candles

    h_close = [ochl["close"] for ochl in hourly_candles]
    h_high = [ochl["high"] for ochl in hourly_candles]
    h_low = [ochl["low"] for ochl in hourly_candles]
    h_volume = [ochl["volume"] for ochl in hourly_candles]
    mfi_1h_period = 48
    if len(h_close) >  mfi_1h_period * 2:
        mfi_1h = talib.MFI(
            high=np.asarray(h_high, dtype=np.double),
            low=np.asarray(h_low, dtype=np.double),
            close=np.asarray(h_close, dtype=np.double),
            volume=np.asarray(h_volume, dtype=np.double),
           timeperiod = mfi_1h_period)
        # np.asarray(h_high, dtype=np.float32),
        # np.asarray(h_low, dtype=np.float32),
        # np.asarray(h_close, dtype=np.float32),
        # np.asarray(h_volume, dtype=np.float32),
    else:
        mfi_1h = [None]

    min_mfi = 30
    min_mfi_long = 40


    last_closes = data["close"][-take_last:]
    last_lows = data["low"][-take_last:]
    last_ccis = cci_data[-take_last:]
    last_adxs = adx_data[-take_last:]

    bbands_above_keltner_up = bbands[0][-1] > kbands['high'][-1]
    bbands_below_keltner_low = bbands[2][-1] < kbands['low'][-1] 

    if r1:
        if past_r1 and past_r1 < r1 and current_price > kbands["high"][-1] and bbands_above_keltner_up:
            state.cooldown[symbol] = True
        elif current_price > r1 and current_price > kbands["high"][-1] and bbands_above_keltner_up:
            state.cooldown[symbol] = True

    if len(data["close"]) > 2:
        if data["close"][-2] < kbands["low"][-2] and current_price > kbands["low"][-1] and bbands_below_keltner_low:
            state.cooldown[symbol] = False
    
    cooldown =  state.cooldown[symbol]
    if not use_cooldown:
        cooldown = False



    #------------------------------#
    # Derivates, Peaks and Valleys #
    #------------------------------#

    """
    This section is not useful yet, possibly use of this to 
    cleanup/confirm signals
    """

    ## TODO


    """
    Classify Market condition (TODO)

    """
    # volatility_state = [-1, 0, 1]
    # trend_state = [-1, 0 ,1]
    # def get_market_state(vol, trend):
    #     if vol == -1 and trend == -1:
    #         return 0
    #     elif vol == -1 and trend == 0:
    #         return 1
    #     elif vol == -1 and trend == 1:
    #         return 2
    #     elif vol == 0 and trend == -1:
    #         return 3
    #     elif vol == 0 and trend == 0:
    #         return 4
    #     elif vol == 0 and trend == 1:
    #         return 5
    #     elif vol == 1 and trend == -1:
    #         return 6
    #     elif vol == 1 and trend == 0:
    #         return 7
    #     elif vol == 1 and trend == 1:
    #         return 8

    indicators_data = {
        "adx": {
            "data": last_adxs.tolist()[-5:]
        },
        "cci": {
            "data": last_ccis.tolist()[-5:]
        },
        "close": {
            "data": last_closes.tolist()[-5:]
        },
        "low": {
            "data": last_lows.tolist()[-5:]
        },
        "cross": {
            "long": ema_long_data.tolist()[-5:],
            "short": ema_short_data.tolist()[-5:]
        },
        "bollinger": {
            "upper": float(bbands[0][-1]), 
            "middle":float(bbands[1][-1]), 
            "lower": float(bbands[2][-1])
        },
        "keltner": {
            "upper": float(kbands["high"][-1]), 
            "middle":float(kbands["middle"][-1]), 
            "lower": float(kbands["low"][-1])
        },
        "cooldown": cooldown
    }


    #--------------------------#
    # Init the PositionManager #
    #--------------------------#

    position_manager = PositionManager(state, symbol, data["timestamp"][-1])
    balance_quoted = state.balance_quoted

    position_manager.set_value(float(amount), update=True)

    # position_manager.set_value(float(amount) + float(
    #    state.positions_manager[symbol]["summary"]["pnl"]), update=True)
    #print(float(amount) + float(
    #    state.positions_manager[symbol]["summary"]["pnl"]))

    #-------------------------------------#
    # Assess Stop loss/take profit limits #
    #-------------------------------------#



    if atr_stop_loss is not None:
        stop_loss, sl_price = atr_tp_sl_percent(
            float(current_price), float(atr), atr_stop_loss, False)
        if max_loss_percent is not None:
            if stop_loss > max_loss_percent:
                stop_loss = max_loss_percent
    if atr_take_profit is not None:
        take_profit, tp_price = atr_tp_sl_percent(
            float(current_price), float(atr), atr_take_profit, True)


    """Place stop loss for manually added positions"""
    if position_manager.has_position and not position_manager.is_stop_placed():
        position_manager.double_barrier(take_profit, stop_loss)


    try:
        #print("BBBB")
        #print(position_manager.position_data["stop_orders"])
        tp_price = position_manager.position_data[
            "stop_orders"]["order_upper"].limit_price
        sl_price = position_manager.position_data[
            "stop_orders"]["order_lower"].limit_price
        data_plot['stop_loss'] = sl_price
        data_plot['take_profit'] = tp_price
    except Exception:
        #print("AAAA")
        #print(position_manager.position_data["stop_orders"])
        pass

    """
    Check entry and stop loss values
    """

    try:
        sl_price = position_manager.position_data[
            "stop_orders"]["order_lower"].limit_price
    except Exception:
         sl_price = None
    entry_price = position_manager.get_entry_price()

    """
    Lift the stop loss at the mid-bollinger if the sl is lower than
    the entry price and the current price passed the middle bband
    """

    # if entry_price and sl_price:
    #     if sl_price < entry_price:
    #         if current_low > bbands[1][-1]:
    #             position_manager.update_double_barrier(
    #                 current_price,
    #                 stop_loss=price_to_percent(
    #                     current_price, bbands[1][-1]))

    """
    If position and the current price is above the mid bollinger
    keep updating the sl to the mid-bollinge
    """

    if lift_sl and position_manager.has_position and sl_price:
        if sl_price < bbands[1][-1]:
            if bbands_below_keltner_low and (
                current_low > bbands[1][-1]):
                position_manager.update_double_barrier(
                    current_price,
                    stop_loss=price_to_percent(
                        current_price, mid_low_point))
                # position_manager.update_double_barrier_price(
                #     current_price,
                #     stop_loss_price=mid_low_point)

    #--------------------------------------------#
    # Feedback on PnL and data collection prints #
    #--------------------------------------------#

    if position_manager.pnl_changed:
        summary_performance = state.positions_manager[symbol]["summary"]
        perf_message = ("%s winning positions %i/%i, realized pnl: %.3f")
        print(
            perf_message % (
                symbol, summary_performance['winning'],
                summary_performance['tot'],
                float(summary_performance['pnl'])))
        perf_message = ("%s winning positions %i/%i, realized pnl: %.3f")
    if int(datetime.fromtimestamp(data["timestamp"][-1] / 1000).minute) == 0:
        if int(datetime.fromtimestamp(data["timestamp"][-1] / 1000).hour) == 0:
            summary_performance = state.positions_manager[symbol]["summary"]
            perf_message = ("%s winning positions %i/%i, realized pnl: %.3f")
            print(
                perf_message % (
                    symbol, summary_performance['winning'],
                    summary_performance['tot'],
                    float(summary_performance['pnl'])))
            perf_message = ("%s winning positions %i/%i, realized pnl: %.3f")


    #----------------------------------------------------#
    # Bayesian Bollinger compute probability indicators  #
    #----------------------------------------------------#
    
    bb_res = bbbayes(
        data["close"], bayes_period,
        bbands[0], bbands[2],
        bbands[1])

    """
    Compute the probability for the previous candle
    """

    bb_res_prev = bbbayes(
        data["close"][:-2], bayes_period,
        bbands[0][:-2], bbands[2][:-2],
        bbands[1][:-2])

    sigma_probs_up = bb_res[0]
    sigma_probs_down = bb_res[1]
    prob_prime = bb_res[2]

    if (sigma_probs_up + sigma_probs_down + prob_prime) == 0:
        state.zero_signal_timer[symbol] += 1
    else:
        state.zero_signal_timer[symbol] = 0

    sigma_probs_up_prev = bb_res_prev[0]
    sigma_probs_down_prev = bb_res_prev[1]
    prob_prime_prev = bb_res_prev[2]

    buy_signal_wait, sell_signal_wait, a, b = compute_signal(
        sigma_probs_up, sigma_probs_down, prob_prime,
        sigma_probs_up_prev, sigma_probs_down_prev,
        prob_prime_prev, lower_threshold, signals_mode)


    #----------------#
    # Resolve signal #
    #----------------#

    buy_signal = False
    sell_signal = False


    # resolve sell signals
    sell_0 = get_signal_from_dict(0, b)
    sell_1 = get_signal_from_dict(1, b)
    sell_2 = get_signal_from_dict(2, b)
    sell_3 = get_signal_from_dict(3, b)
    sell_4 = get_signal_from_dict(4, b)
    sell_5 = get_signal_from_dict(5, b)
    # resolve buy signals
    buy_0 = get_signal_from_dict(0, a)
    buy_1 = get_signal_from_dict(1, a)
    buy_2 = get_signal_from_dict(2, a)
    buy_3 = get_signal_from_dict(3, a)
    buy_4 = get_signal_from_dict(4, a)
    buy_5 = get_signal_from_dict(5, a)
    


    ema_filter_override = False

    default_trade_data = {
        "signal_type": None,
        "status": None,
        "n_active": 0,
        "level": 0
    }


    """
    Filter using keltner channels
    """
    keltner_filter_on = False
    if keltner_filter:
        if bbands_above_keltner_up and bbands_below_keltner_low:
            #keltner_filter_on = True
            buy_signal_wait = False

    """
    Skip the ema filter if the keltner mid line is
    above the bollinger mid line
    """
    if bbands[1][-1] > kbands["middle"][-1]:
        if not bbands_above_keltner_up and not bbands_below_keltner_low:
            ema_filter_override = True        

    """
    Filter with ema
    """
    if not ema_filter_override and ema_filter:
        if buy_signal_wait and ema_long > ema_short:
            buy_signal_wait = False

    # """
    # Filter signals in a bearish-ranging region
    # """ 
    # if current_price < pivot and current_price > s1:
    #     buy_signal_wait = False

    """
    Filter buy orders when long mfi gives too much
    oversold signal
    """  
    if mfi_1h[-1]:
        if mfi_1h[-1] < min_mfi:
            buy_signal_wait = False

    """
    Filter sell orders when break up
    """
    if bbands_above_keltner_up:
        if ema_long < ema_short:
            sell_signal_wait = False
    """
    Cancel out a buy signal if a sell signal is also
    fired in the same candle
    """
    if sell_signal_wait:
        buy_signal_wait = False

    # if len(macd_1h) == 3:
    #     if macd_1h[0][-1]:
    #         if (macd_1h[2][-1] < macd_1h[2][-2] and macd_1h[2][-1] > 0):
    #             if keltner_filter_on:
    #                 buy_signal_wait = False
    #     elif keltner_filter_on:
    #         buy_signal_wait = False

    # if len(macd_1h) == 3:
    #     if macd_1h[0][-1]:
    #         if macd_1h[0][-1] < 0.001:
    #             buy_signal_wait = False


    """
    Start the wait/check/stop process
    """
    if position_manager.check_if_waiting():
        trade_data, trade_message = position_manager.waiting_data()
        trade_data["n_active"] += 1
        #if trade_data["n_active"] > keep_signal:
        if trade_data["status"] == "buying" and trade_data["n_active"] > keep_signal:
            """
            If the waiting eceeded the keep_signal limit
            reset the trade object and stop waiting
            """
            position_manager.stop_waiting()
            trade_message = None
            trade_data = default_trade_data

        if position_manager.has_position and trade_data["status"] == "buying":
            position_manager.stop_waiting()
            trade_message = None
            trade_data = default_trade_data
        elif not position_manager.has_position and trade_data["status"] == "selling":
            position_manager.stop_waiting()
            trade_message = None
            trade_data = default_trade_data
    else:
        trade_message = None
        trade_data = default_trade_data


    """
    Reset the trade data when a new signal pops up
    """
    if  not position_manager.has_position and buy_signal_wait :
        trade_data = default_trade_data
        trade_data["status"] = "buying"
        if buy_0:
            trade_data["signal_type"] = 0
        elif buy_1:
            trade_data["signal_type"] = 1
        elif buy_5:
            trade_data["signal_type"] = 5
        elif buy_3:
            trade_data["signal_type"] = 3
        elif buy_4:
            trade_data["signal_type"] = 4
        position_manager.start_waiting(trade_data, "waiting to buy")
    elif position_manager.has_position and sell_signal_wait:
        trade_data = default_trade_data
        trade_data["status"] = "selling"
        if sell_0:
            trade_data["signal_type"] = 0
        elif sell_1:
            trade_data["signal_type"] = 1
        elif sell_5:
            trade_data["signal_type"] = 5
        elif sell_3:
            trade_data["signal_type"] = 3
        elif sell_4:
            trade_data["signal_type"] = 4
        position_manager.start_waiting(trade_data, "waiting to sell")


    """
    define a dictionary with the confirmation function
    """
    confirmation_functions = {
        "buy": {
            "signal_0": signal_buy_cooldown,
            "signal_1": signal_buy_cooldown,         
            "signal_3": signal_no_wait,
            "signal_4": signal_no_wait,
            "signal_5": signal_buy_cooldown
        },
        "sell": {
            "signal_0": signal_sell_cci,
            "signal_1": signal_sell_cci,
            "signal_3": signal_no_wait,
            "signal_4": signal_no_wait,
            "signal_5": signal_sell_cci
        }
    }
    """
    If the position is waiting we need to check for confirmation
    """
    if position_manager.check_if_waiting():
        if trade_data["status"] == "buying":
            buy_signal = confirmation_functions["buy"]["signal_%i" %
                trade_data["signal_type"]](
                    position_manager, trade_data, indicators_data)
        elif trade_data["status"] == "selling":
            sell_signal = confirmation_functions["sell"]["signal_%i" %
                trade_data["signal_type"]](
                    position_manager, trade_data, indicators_data)


    #-------------------------------------------------#
    # Assess available balance and target trade value #
    #-------------------------------------------------#

    skip_buy = False
    if balance_quoted <= position_manager.position_value and not position_manager.has_position:
        if balance_quoted < 20:
            print(
                "WARNING: Balance quoted (%s) is less than "
                "the minimum buy amount (%s)." % (
                    balance_quoted, position_manager.position_value))
            skip_buy = True
        else:
            position_manager.set_value(
                balance_quoted * 0.95, update=True)


    # is_rising = indicator_is_rising(
    #     data["close"].select('close'),
    #      kbands['high'],
    #     cci_data.select("cci"))
    # if position_manager.has_position:
    #     if is_rising[0] == False and is_rising[1] == -1:
    #         sell_signal = True

    """
    Set a narrow stop loss if attempting to catch up the trend
    """

    if lift_sl and buy_signal and (bbands_below_keltner_low and
        current_price > bbands[1][-1]):
        stop_loss = price_to_percent(
            current_price, mid_low_point)

    #--------------#
    # Plot section #
    #--------------#
    data_plot['prob_prime'] = prob_prime
    data_plot['sigma_up'] = sigma_probs_up
    data_plot['sigma_down'] = sigma_probs_down
    plot(symbol, data_plot)
    # with PlotScope.root(symbol):
    #     plot("k_ema", kbands["middle"][-1])
    #     plot("k_upper", kbands["high"][-1])
    #     plot("k_lower", kbands["low"][-1])
    #     if kbands_1h["middle"][0]:
    #         plot("k_ema_1h", kbands_1h["middle"][-1])
    #         plot("k_upper_1h", kbands_1h["high"][-1])
    #         plot("k_lower_1h", kbands_1h["low"][-1])


    # with PlotScope.root(symbol):
    #     plot("daily_resistance", r1)
    #     plot("daily_support", s1)
    #     plot("pivot", pivot)

    # try:
    #     tp_price = position_manager.position_data[
    #         "stop_orders"]["order_upper"].stop_price
    #     sl_price = position_manager.position_data[
    #         "stop_orders"]["order_lower"].stop_price
    #     with PlotScope.root(position_manager.symbol):
    #         plot("tp", tp_price)
    #         plot("sl", sl_price)
    # except Exception:
    #     pass

    # with PlotScope.group("bayesian_bollinger", symbol):
    #     plot("sigma_up", sigma_probs_up)
    #     plot("sigma_down", sigma_probs_down)
    #     plot("prime_prob", prob_prime)

    # with PlotScope.group("cooldown", symbol):
    #     plot("cooldown", int(cooldown))

    # with PlotScope.group("hourly_mf1", symbol):
    #     if mfi_1h[-1]:
    #         plot("mfi_1h", mfi_1h[-1])
    #     if mfi_1h_long[-1]:
    #         plot("mfi_1h_long", mfi_1h_long[-1])


    # with PlotScope.group("hourly_macd", symbol):
    #     if len(macd_1h) == 3:
    #         if macd_1h[0][-1]:
    #             plot("macd", macd_1h[0][-1])
    #             plot("macd_signal", macd_1h[1][-1])
    #             plot("macd_hist", macd_1h[2][-1])

    # with PlotScope.group("pnl", symbol):
    #     plot("pnl", float(state.positions_manager[
    #         symbol]["summary"]['pnl']))


    # with PlotScope.group("signal", symbol):
    #     plot("0", int(a["0"]) + (-1 * int(b["0"])))
    #     try:
    #         plot("1", int(a["1"]) + (-1 * int(b["1"])))
    #     except KeyError:
    #         pass
    #     try:
    #         plot("2", int(a["2"]) + (-1 * int(b["2"])))
    #     except KeyError:
    #         pass
    #     try:
    #         plot("3", int(a["3"]) + (-1 * int(b["3"])))
    #     except KeyError:
    #         pass
    #     try:
    #         plot("4", int(a["4"]) + (-1 * int(b["4"])))
    #     except KeyError:
    #         pass
    #     try:
    #         plot("5", int(a["5"]) + (-1 * int(b["5"])))
    #     except KeyError:
    #         pass


    #----------------------#
    # Buy/Sell instruction #
    #----------------------#

    if buy_signal and not position_manager.has_position:
        signal_msg_data = {
            "symbol": symbol,
            "value": position_manager.position_value,
            "current_price": current_price}
        signal_msg = (
            "++++++\n"
            "Buy Signal: creating market order for %(symbol)s\n"
            "Buy value: %(value)s at current market price %(current_price)f\n"
            "++++++\n")
        skip_msg = (
            "++++++\n"
            "Skip buy market order for %(symbol)s\n"
            "Not enough balance: %(value)s at current market price %(current_price)f\n"
            "++++++\n")
        # print(signal_msg % signal_msg_data)
        # position_manager.open_market()
        # position_manager.double_barrier(take_profit, stop_loss)
        # if collect_data:
        #     position_manager.collect_data(state, indicators_data)
        if skip_buy is False:
            state.balance_quoted -= position_manager.position_value
            position_manager.open_market()
            #position_manager.double_barrier(take_profit, stop_loss)
            if collect_data:
                position_manager.collect_data(state, indicators_data)
            print(signal_msg % signal_msg_data)

        else:
            print(skip_msg % signal_msg_data)


    elif sell_signal and position_manager.has_position:
        signal_msg_data = {
            "symbol": symbol,
            "amount": position_manager.position_exposure(),
            "current_price": current_price}
        signal_msg = (
            "++++++\n"
            "Sell Signal: creating market order for %(symbol)s\n"
            "Sell amount: %(amount)s at current market price %(current_price)f\n"
            "++++++\n")
        print(signal_msg % signal_msg_data)
        position_manager.close_market()


##+------------------------------------------------------------------+
##| methods and helpers                                              |
##+------------------------------------------------------------------+

def get_default_params(state, symbol):
    default_params = state.params["DEFAULT"]
    try:
        params = state.params[symbol]
        for key in default_params:
            if key not in params.keys():
                params[key] = default_params[key]
    except KeyError:
        params = default_params
    return params


def cross_over(x, y):
    if y[1] < x[1]:
        return False
    else:
        if x[0] > y[0]:
            return True
        else:
            return False


def cross_under(x, y):
    if y[1] > x[1]:
        return False
    else:
        if x[0] < y[0]:
            return True
        else:
            return False

def get_signal_from_dict(signal_id, signal_dict):
    try:
        signal = signal_dict['%i' % signal_id]
    except KeyError:
        signal = False
    return signal

def price_to_percent(close, price):
    return abs(price - close) / close

def atr_tp_sl_percent(close, atr, n=6, tp=True):
    if tp is True:
        tp = close + (n * atr)
    else:
        tp = close - (n * atr)
    return (price_to_percent(close, tp), tp)


class PositionManager:
    """
    A simple helper to manage positions boilerplate functionalities.
    It wraps around and extends the Trality position functionalities.
        - Query for open position (query_open_position_by_symbol)
        - Store the orders relative to the current position in state
          - A position can be declared without the orders to be filled/placed yet:
            waiting confirmation (TODO) or waiting filling limit orders (TODO)
          - Stop orders can be declared by the same class that opens the position
            getting all the info and storing the stop orders objects with the
            current corresponding symbol-position with the other orders
        - Keep track of per-symbols pnl and winning/losing records (extending the
          base position implementation where it's impossible to record pnl of a position
          terminated by a stop order before the first candle)
    propose syntax:
        position_manager = PositionManager(state, "BTCUSDT")
    query if has position:
        position_manager.has_position
    Set a value to the position
        position_manager.set_value(position_value)
    open the position:
        position_manager.open_market()
    save things in state without placing orders (eg waiting for confirmation):
        position_manager.open_wait_confirmation()
        # this will set True to the attribute position_manager.is_pending 
    open a position with a limit order and deal with the pending status:
        position_manager.open_limit(price_limit)
        .... need to think a clean pattern for limit/if_touched/trailing orders
    check if stop orders are present and add them if not:
        if not position_manager.has_double_barrier:
            position_manager.double_barrier(
                stop_loss=0.1, take_profit=0.05)
    close the position:
        position_manager.close_market()
    """


    def __init__(self, state, symbol, timestamp, include_dust=False):
        position = get_open_position(symbol, side = 'LONG')
        self.symbol = symbol
        self.timestamp = int(timestamp)
        self.has_position = position is not None
        self.is_pending = False
        self.pnl_changed = False
        try:
            self.position_data = state.positions_manager[self.symbol]["data"]
        except AttributeError:
            state.positions_manager = {}
            state.positions_manager[self.symbol] = {
                "data": self.default_data(),
                "summary": {
                    "last_closure_type": None, "last_pnl": 0, "winning": 0, "tot": 0, "pnl": 0}}
            self.position_data = state.positions_manager[self.symbol]["data"]
        except KeyError:
            state.positions_manager[self.symbol] = {
                "data": self.default_data(),
                "summary": {
                    "last_closure_type": None, "last_pnl": 0, "winning": 0, "tot": 0, "pnl": 0}}
            self.position_data = state.positions_manager[self.symbol]["data"]
        if self.has_position:
            self.position_data["position"] = position
            if self.position_data["buy_order"] is None:
                # Potential manual buy or existing positions
                # when the bot was started
                order_id = self.position_data["position"].order_ids[-1]
                self.position_data["buy_order"] = query_order(order_id)

        #TODO self.check_if_waiting()
        #TODO self.check_if_pending()
        if not self.has_position and not self.is_pending:
            if self.position_data["buy_order"] is not None:
                stop_orders_filled = self.is_stop_filled()
                if stop_orders_filled:
                    state.positions_manager[
                        self.symbol]["summary"][
                            "last_closure_type"] = stop_orders_filled["side"]
                else:
                    state.positions_manager[
                        self.symbol]["summary"][
                            "last_closure_type"] = "rule"                    
                try:
                    closed_position = self.position_data["position"]
                except KeyError:
                    closed_position = None
                if closed_position is not None:
                    pnl = float(closed_position.pnl)
                    if pnl > 0:
                        state.positions_manager[self.symbol]["summary"]["winning"] += 1
                    state.positions_manager[self.symbol]["summary"]["tot"] += 1
                    state.positions_manager[self.symbol]["summary"]["pnl"] += pnl
                    state.positions_manager[self.symbol]["summary"]["last_pnl"] = pnl
                    try:
                        if state.collect_data:
                            state.collect_data[
                                self.symbol][
                                    str(closed_position.entry_time)]["pnl"] = pnl
                    except KeyError:
                        pass
                    self.pnl_changed = True
                else:
                    if stop_orders_filled:
                        sold_value = float((
                            stop_orders_filled[
                                "order"].executed_quantity * stop_orders_filled[
                                    "order"].executed_price) - stop_orders_filled[
                                        "order"].fees)
                        pnl = sold_value - self.position_value()
                        if pnl > 0:
                            state.positions_manager[self.symbol]["summary"]["winning"] += 1
                        state.positions_manager[self.symbol]["summary"]["tot"] += 1
                        state.positions_manager[self.symbol]["summary"]["pnl"] += pnl
                        state.positions_manager[self.symbol]["summary"]["last_pnl"] = pnl
                        try:
                            if state.collect_data:
                                state.collect_data[
                                    self.symbol][str(
                                        stop_orders_filled["order"].created_time)]["pnl"] = pnl
                        except KeyError:
                            pass
                        self.pnl_changed = True

                # reset state and position data
                self.cancel_stop_orders()
                waiting_data = self.position_data["waiting"]
                state.positions_manager[self.symbol]["data"] = self.default_data()
                self.position_data = state.positions_manager[self.symbol]["data"]
                self.position_data["waiting"] = waiting_data
            self.cancel_stop_orders()

    
    def set_value(self, value, update=False):
        try:
            stored_value = self.position_data["value"]
        except KeyError:
            stored_value = None
        if stored_value is None:
           self.position_data["value"] = value 
           self.position_value = value
        else:
            self.position_value = stored_value
        if update:
            self.position_value = value

    def get_entry_price(self):
        entry_price = None
        if self.has_position:
            try:
                entry_price = float(
                    self.position_data["position"].entry_price)
            except Exception:
                pass
        return entry_price

    def open_market(self, add=False):
        try:
            buy_order = self.position_data["buy_order"]
        except KeyError:
            buy_order = None
        if buy_order is None:        
            buy_order = order_market_value(
                symbol=self.symbol, value=self.position_value, leverage = FUTURES_LEVERAGE)
            self.position_data["buy_order"] = buy_order
            #self.__update_state__()
        elif add == True:
            buy_order = order_market_value(
                symbol=self.symbol, value=self.position_value)
            self.position_data["buy_order"] = buy_order            
        else:
            print("Buy order already placed")
        # if self.check_if_waiting():
        #     self.stop_waiting()

    def close_market(self):
        if self.has_position:
            close_position(self.symbol)
            #amount = self.position_amount()
            #order_market_amount(self.symbol,-1 * subtract_order_fees(amount))
            self.cancel_stop_orders()
        # if self.check_if_waiting():
        #     self.stop_waiting()

    def double_barrier(self, take_profit, stop_loss, subtract_fees=False):
        try:
            stop_orders = self.position_data["stop_orders"]
        except KeyError:
            stop_orders = {
                "order_upper": None, "order_lower": None}
        if stop_orders["order_upper"] is None:
            amount = self.position_amount()
            #amount = self.position_exposure()
            if amount is None:
                print("No amount to sell in position")
                return
            elif amount > 0:
                amount = -1 * amount
            # with OrderScope.one_cancels_others():
            #     stop_orders["order_upper"] = order_take_profit(
            #         self.symbol, amount, take_profit, subtract_fees=subtract_fees)
            #     stop_orders["order_lower"] = order_stop_loss(
            #         self.symbol, amount, stop_loss, subtract_fees=subtract_fees)
            stop_orders["order_upper"] = order_if_percent_touched_amount(
                self.symbol, amount, take_profit, 1, 1)
            stop_orders["order_lower"] = order_if_percent_touched_amount(
                self.symbol, amount, -1 * stop_loss, 1, -1)
            # if stop_orders["order_upper"].status != OrderStatus.Pending or stop_orders["order_upper"].status != OrderStatus.Created:
            #     errmsg = "make_double barrier failed with: {}"
            #     raise ValueError(errmsg.format(stop_orders["order_upper"].error))
            self.position_data["stop_orders"] = stop_orders
        else:
            print("Stop orders already exist")

    def double_barrier_price(self, take_profit_price, stop_loss_price, subtract_fees=False):
        try:
            stop_orders = self.position_data["stop_orders"]
        except KeyError:
            stop_orders = {
                "order_upper": None, "order_lower": None}
        if stop_orders["order_upper"] is None:
            amount = self.position_amount()
            #amount = self.position_exposure()
            if amount is None:
                print("No amount to sell in position")
                return
            with OrderScope.one_cancels_others():
                stop_orders["order_upper"] = order_iftouched_market_amount(
                    self.symbol, -1 * amount, take_profit_price)
                stop_orders["order_lower"] = order_iftouched_market_amount(
                    self.symbol, -1 * amount, stop_loss_price)
            if stop_orders["order_upper"].status != OrderStatus.Pending:
                errmsg = "make_double barrier failed with: {}"
                raise ValueError(errmsg.format(stop_orders["order_upper"].error))
            self.position_data["stop_orders"] = stop_orders
        else:
            print("Stop orders already exist")

    def is_stop_filled(self):
        try:
            stop_orders = self.position_data["stop_orders"]
            stop_loss = stop_orders["order_lower"]
            take_profit = stop_orders["order_upper"]
        except KeyError:
            return None
        if stop_loss is not None:
            stop_loss.refresh()
            if stop_loss.is_filled():
                return {"side": "stop_loss", "order": stop_loss}
        if take_profit is not None:
            take_profit.refresh()
            if take_profit.is_filled():
                return {"side": "take_profit", "order": take_profit}

    def is_stop_placed(self):
        try:
            stop_orders = self.position_data["stop_orders"]
            stop_loss = stop_orders["order_lower"]
            take_profit = stop_orders["order_upper"]
        except KeyError:
            return False
        if stop_loss is None and take_profit is None:
            return False
        else:
            return True

    def update_double_barrier(self, current_price, take_profit=None, stop_loss=None, subtract_fees=False):
        success = True
        if take_profit is None:
            # keep upper as it is
            try:
                order_upper_price = float(self.position_data[
                    "stop_orders"]["order_upper"].limit_price)
                take_profit = abs(
                    order_upper_price - current_price) / current_price
            except:
                success = False
        if stop_loss is None:
            # Keep low as it is
            try:
                order_lower_price = float(self.position_data[
                    "stop_orders"]["order_lower"].limit_price)
                stop_loss = abs(
                    order_lower_price - current_price) / current_price
            except:
                success = False
        if success:
            self.cancel_stop_orders()
            self.double_barrier(
                take_profit, stop_loss, subtract_fees=subtract_fees)
        else:
            print("update stop limits failed")

    def update_double_barrier_price(self, current_price, take_profit_price=None, stop_loss_price=None, subtract_fees=False):
        success = True
        if take_profit_price is None:
            # keep upper as it is
            try:
                take_profit_price = float(self.position_data[
                    "stop_orders"]["order_upper"].limit_price)
            except:
                success = False
        if stop_loss_price is None:
            # Keep low as it is
            try:
                stop_loss_price = float(self.position_data[
                    "stop_orders"]["order_lower"].limit_price)
            except:
                success = False
        if success:
            self.cancel_stop_orders()
            self.double_barrier_price(
                take_profit_price, stop_loss_price, subtract_fees=subtract_fees)
        else:
            print("update stop limits failed")

    def position_amount(self):
        try:
            amount = float(self.position_data["buy_order"].quantity)
        except Exception:
            amount = None
        return amount

    def position_value(self):
        try:
            buy_order = self.position_data["buy_order"]
            buy_order.refresh()
            value = float(
                (buy_order.executed_quantity * buy_order.executed_price) - buy_order.fees)
        except KeyError:
            value = None
        return value

    def position_exposure(self):
        try:
            exposure = float(self.position_data["position"].quantity)
        except KeyError:
            exposure = None
        return exposure       
    
    def cancel_stop_orders(self):
        try:
            stop_orders = self.position_data["stop_orders"]
        except KeyError:
            stop_orders = {
                "order_upper": None, "order_lower": None}
        for stop_level in stop_orders:
            if stop_orders[stop_level] is not None:
                try:
                    stop_orders[stop_level].cancel()
                    #cancel_order(stop_orders[stop_level].id)
                    stop_orders[stop_level] = None
                except Exception:
                    pass
        self.position_data["stop_orders"] = stop_orders
    
    def collect_data(self, state, data_dict):
        if state.collect_data is None:
            state.collect_data = {}
        try:
            state.collect_data[self.symbol]["%s" % self.timestamp] = data_dict
        except KeyError:
            state.collect_data[self.symbol] = {}
            state.collect_data[self.symbol]["%s" % self.timestamp] = data_dict        
    
    def start_waiting(self, waiting_data=None, waiting_message=None):
        if waiting_data:
            self.position_data["waiting"]["data"] = waiting_data
        if waiting_message:
            self.position_data["waiting"]["message"] = waiting_message
        self.position_data["waiting"]["status"] = True

    def stop_waiting(self, waiting_data=None, waiting_message=None):
        self.position_data["waiting"]["status"] = False
        self.position_data["waiting"]["data"] = waiting_data
        self.position_data["waiting"]["message"] = waiting_message

    def check_if_waiting(self):
        if self.position_data["waiting"]["status"] is None:
            return False
        else:
            return self.position_data["waiting"]["status"]

    def waiting_data(self):
        return (
            self.position_data["waiting"]["data"],
            self.position_data["waiting"]["message"])

    def default_data(self):
        return {
            "stop_orders": {"order_upper": None, "order_lower": None},
            "position": None,
            "waiting": {"status": None, "data": None, "message": None},
            "buy_order": None,
            "value": None
        }


def keltner_channels(data, period=20, atr_period=10, kc_mult=2, take_last=50):
    """
    calculate keltner channels mid, up and low values
    """
    ema = talib.EMA(
        data["close"], timeperiod=period)
    atr = talib.ATR(
        data['high'], data['low'], data['close'],
        timeperiod=atr_period)
    high = ema[-take_last:] + (kc_mult * atr[-take_last:])
    low = ema[-take_last:] - (kc_mult * atr[-take_last:])
    return {'middle': ema, 'high': high, 'low': low}



def bbbayes(close, bayes_period, bb_upper, bb_basis, sma_values):
    prob_bb_upper_up_seq = greater(close[-bayes_period:],
    bb_upper[-bayes_period:])
    prob_bb_upper_down_seq = less(close[-bayes_period:],
    bb_upper[-bayes_period:])
    prob_bb_basis_up_seq = greater(close[-bayes_period:],
    bb_basis[-bayes_period:])
    prob_bb_basis_down_seq = less(close[-bayes_period:],
    bb_basis[-bayes_period:])
    prob_sma_up_seq = greater(close[-bayes_period:],
    sma_values[-bayes_period:])
    prob_sma_down_seq = less(close[-bayes_period:],
    sma_values[-bayes_period:])
    
    prob_bb_upper_up = sum(
        prob_bb_upper_up_seq) / bayes_period
    prob_bb_upper_down = sum(
        prob_bb_upper_down_seq) / bayes_period
    prob_up_bb_upper = prob_bb_upper_up / (prob_bb_upper_up + prob_bb_upper_down)
    prob_bb_basis_up = sum(
        prob_bb_basis_up_seq) / bayes_period
    prob_bb_basis_down = sum(
        prob_bb_basis_down_seq) / bayes_period
    prob_up_bb_basis = prob_bb_basis_up / (prob_bb_basis_up + prob_bb_basis_down)

    prob_sma_up = sum(
        prob_sma_up_seq) / bayes_period
    prob_sma_down = sum(
        prob_sma_down_seq) / bayes_period
    prob_up_sma = prob_sma_up / (prob_sma_up + prob_sma_down)

    sigma_probs_down = nan_to_num(
        prob_up_bb_upper * prob_up_bb_basis * prob_up_sma / prob_up_bb_upper * prob_up_bb_basis * prob_up_sma + (
            (1 - prob_up_bb_upper) * (1 - prob_up_bb_basis) * (
                1 - prob_up_sma)), 0)
    # Next candles are breaking Up
    prob_down_bb_upper = prob_bb_upper_down / (
        prob_bb_upper_down + prob_bb_upper_up)
    prob_down_bb_basis = prob_bb_basis_down / (
        prob_bb_basis_down + prob_bb_basis_up)
    prob_down_sma = prob_sma_down / (prob_sma_down + prob_sma_up)
    sigma_probs_up = nan_to_num(
        prob_down_bb_upper * prob_down_bb_basis * prob_down_sma / prob_down_bb_upper * prob_down_bb_basis * prob_down_sma + (
            (1 - prob_down_bb_upper) * (1 - prob_down_bb_basis) * (1 - prob_down_sma) ), 0)

    prob_prime = nan_to_num(
        sigma_probs_down * sigma_probs_up / sigma_probs_down * sigma_probs_up + (
            (1 - sigma_probs_down) * (1 - sigma_probs_up)), 0)
    return(sigma_probs_up, sigma_probs_down, prob_prime)

def compute_signal(
    sigma_probs_up, sigma_probs_down, prob_prime,sigma_probs_up_prev,
    sigma_probs_down_prev, prob_prime_prev, lower_threshold=15, n_signals=4):
    buy_signal_record = {"0": False}
    sell_signal_record = {"0": False}
    for signal_index in n_signals:
        buy_signal_record["%i" % signal_index] = False
        sell_signal_record["%i" % signal_index] = False

    lower_threshold_dec = lower_threshold / 100.0
    sell_using_prob_prime = prob_prime > lower_threshold_dec and prob_prime_prev == 0
    sell_base_signal = sigma_probs_up < 1 and sigma_probs_up_prev == 1
    buy_using_prob_prime = prob_prime == 0 and prob_prime_prev > lower_threshold_dec
    buy_base_signal = sigma_probs_down < 1 and sigma_probs_down_prev == 1
    buy_signal_record["0"] = buy_base_signal or buy_using_prob_prime
    sell_signal_record["0"] = sell_base_signal or sell_using_prob_prime
    sell_using_sigma_probs_up = [sell_base_signal]
    buy_using_sigma_probs_down = [buy_base_signal]
    if 1 in n_signals:
        signal_1_sell = sigma_probs_down_prev == 0 and sigma_probs_down > 0
        signal_1_buy = sigma_probs_up_prev == 0 and sigma_probs_up > 0
        buy_signal_record["%i" % 1] = signal_1_buy
        sell_signal_record["%i" % 1] = signal_1_sell
        sell_using_sigma_probs_up.append(signal_1_sell)
        buy_using_sigma_probs_down.append(signal_1_buy)
    if 2 in n_signals:
        signal_2_sell = sigma_probs_down_prev < 1 and sigma_probs_down == 1
        signal_2_buy = sigma_probs_up_prev > 0 and sigma_probs_up == 0
        buy_signal_record["%i" % 2] = signal_2_buy
        sell_signal_record["%i" % 2] = signal_2_sell
        sell_using_sigma_probs_up.append(signal_2_sell)
        buy_using_sigma_probs_down.append(signal_2_buy)
    buy_using_sigma_probs_down_cross = cross_over(
        [prob_prime_prev, prob_prime], [sigma_probs_down_prev, sigma_probs_down])
    sell_using_sigma_probs_down_cross = cross_under(
        [prob_prime_prev, prob_prime], [sigma_probs_down_prev, sigma_probs_down])
    if 3 in n_signals:
        signal_3_sell = sell_using_sigma_probs_down_cross and max(
            [prob_prime_prev, prob_prime]) > lower_threshold_dec
        signal_3_buy = buy_using_sigma_probs_down_cross and max(
            [prob_prime_prev, prob_prime]) > lower_threshold_dec
        buy_signal_record["%i" % 3] = signal_3_buy
        sell_signal_record["%i" % 3] = signal_3_sell
        sell_using_sigma_probs_up.append(signal_3_sell)
        buy_using_sigma_probs_down.append(signal_3_buy)
    buy_using_sigma_probs_up_cross = cross_over(
        [prob_prime_prev, prob_prime], [sigma_probs_up_prev, sigma_probs_up])
    sell_using_sigma_probs_up_cross = cross_under(
        [prob_prime_prev, prob_prime], [sigma_probs_up_prev, sigma_probs_up])
    if 4 in n_signals:
        signal_4_sell = False
        signal_4_buy = (
            sell_using_sigma_probs_up_cross and max(
                [prob_prime_prev, prob_prime]) > lower_threshold_dec) or (
                    buy_using_sigma_probs_up_cross and max(
                        [prob_prime_prev, prob_prime]) > lower_threshold_dec)
        buy_signal_record["%i" % 4] = signal_4_buy
        sell_signal_record["%i" % 4] = signal_4_sell
        # sell_using_sigma_probs_up.append(
        #     sell_using_sigma_probs_up_cross and max([prob_prime_prev, prob_prime]) > lower_threshold_dec)
        buy_using_sigma_probs_down.append(signal_4_buy)
    if 5 in n_signals:
        signal_5_sell = False
        signal_5_buy = sigma_probs_up > sigma_probs_down and sigma_probs_up > prob_prime and sigma_probs_up_prev > sigma_probs_up
        buy_signal_record["%i" % 5] = signal_5_buy
        sell_signal_record["%i" % 5] = signal_5_sell
        buy_using_sigma_probs_down.append(signal_5_buy)
        # sell_using_sigma_probs_up.append(
        #         sigma_probs_down_prev < 1 and sigma_probs_down == 1 and sigma_probs_down > sigma_probs_up and sigma_probs_down > prob_prime and sigma_probs_down)
    sell_signal = sell_using_prob_prime or any(sell_using_sigma_probs_up)
    buy_signal = buy_using_prob_prime or any(buy_using_sigma_probs_down)
    return (buy_signal, sell_signal, buy_signal_record, sell_signal_record)


def compute_signal(
    sigma_probs_up, sigma_probs_down, prob_prime,sigma_probs_up_prev,
    sigma_probs_down_prev, prob_prime_prev, lower_threshold=15, n_signals=4):
    buy_signal_record = {"0": False}
    sell_signal_record = {"0": False}
    small_offset = 0.001
    for signal_index in n_signals:
        buy_signal_record["%i" % signal_index] = False
        sell_signal_record["%i" % signal_index] = False

    lower_threshold_dec = lower_threshold / 100.0
    sell_using_prob_prime = prob_prime > lower_threshold_dec and prob_prime_prev == 0
    sell_base_signal = sigma_probs_up < 1 and sigma_probs_up_prev == 1
    buy_using_prob_prime = prob_prime == 0 and prob_prime_prev > lower_threshold_dec
    buy_base_signal = sigma_probs_down < 1 and sigma_probs_down_prev == 1
    buy_signal_record["0"] = buy_base_signal or buy_using_prob_prime
    sell_signal_record["0"] = sell_base_signal or sell_using_prob_prime
    sell_using_sigma_probs_up = [sell_base_signal]
    buy_using_sigma_probs_down = [buy_base_signal]
    if 1 in n_signals:
        signal_1_sell = sigma_probs_down_prev == 0 and sigma_probs_down > (0 + small_offset)
        signal_1_buy = sigma_probs_up_prev == 0 and sigma_probs_up > (0 + small_offset)
        buy_signal_record["%i" % 1] = signal_1_buy
        sell_signal_record["%i" % 1] = signal_1_sell
        sell_using_sigma_probs_up.append(signal_1_sell)
        buy_using_sigma_probs_down.append(signal_1_buy)
    if 2 in n_signals:
        signal_2_sell = sigma_probs_down_prev < (1 - small_offset) and sigma_probs_down == 1
        signal_2_buy = sigma_probs_up_prev > (0 + small_offset) and sigma_probs_up == 0
        buy_signal_record["%i" % 2] = signal_2_buy
        sell_signal_record["%i" % 2] = signal_2_sell
        sell_using_sigma_probs_up.append(signal_2_sell)
        buy_using_sigma_probs_down.append(signal_2_buy)
    buy_using_sigma_probs_down_cross = cross_over(
        [prob_prime_prev, prob_prime], [sigma_probs_down_prev, sigma_probs_down])
    sell_using_sigma_probs_down_cross = cross_under(
        [prob_prime_prev, prob_prime], [sigma_probs_down_prev, sigma_probs_down])
    if 3 in n_signals:
        signal_3_sell = sell_using_sigma_probs_down_cross and max(
            [prob_prime_prev, prob_prime]) > lower_threshold_dec
        signal_3_buy = buy_using_sigma_probs_down_cross and max(
            [prob_prime_prev, prob_prime]) > lower_threshold_dec
        buy_signal_record["%i" % 3] = signal_3_buy
        sell_signal_record["%i" % 3] = signal_3_sell
        sell_using_sigma_probs_up.append(signal_3_sell)
        buy_using_sigma_probs_down.append(signal_3_buy)
    buy_using_sigma_probs_up_cross = cross_over(
        [prob_prime_prev, prob_prime], [sigma_probs_up_prev, sigma_probs_up])
    sell_using_sigma_probs_up_cross = cross_under(
        [prob_prime_prev, prob_prime], [sigma_probs_up_prev, sigma_probs_up])
    if 4 in n_signals:
        signal_4_sell = False
        signal_4_buy = (
            sell_using_sigma_probs_up_cross and max(
                [prob_prime_prev, prob_prime]) > lower_threshold_dec) or (
                    buy_using_sigma_probs_up_cross and max(
                        [prob_prime_prev, prob_prime]) > lower_threshold_dec)
        buy_signal_record["%i" % 4] = signal_4_buy
        sell_signal_record["%i" % 4] = signal_4_sell
        # sell_using_sigma_probs_up.append(
        #     sell_using_sigma_probs_up_cross and max([prob_prime_prev, prob_prime]) > lower_threshold_dec)
        buy_using_sigma_probs_down.append(signal_4_buy)
    if 5 in n_signals:
        signal_5_sell = False
        signal_5_buy = False
        if sigma_probs_up > small_offset and sigma_probs_up > small_offset and sigma_probs_up_prev > small_offset:
             signal_5_buy = sigma_probs_up > sigma_probs_down and sigma_probs_up > prob_prime and sigma_probs_up_prev > sigma_probs_up
        buy_signal_record["%i" % 5] = signal_5_buy
        sell_signal_record["%i" % 5] = signal_5_sell
        buy_using_sigma_probs_down.append(signal_5_buy)
        # sell_using_sigma_probs_up.append(
        #         sigma_probs_down_prev < 1 and sigma_probs_down == 1 and sigma_probs_down > sigma_probs_up and sigma_probs_down > prob_prime and sigma_probs_down)
    sell_signal = sell_using_prob_prime or any(sell_using_sigma_probs_up)
    buy_signal = buy_using_prob_prime or any(buy_using_sigma_probs_down)
    return (buy_signal, sell_signal, buy_signal_record, sell_signal_record)


def get_yesterday_daily_candle(data):
    today = datetime.fromtimestamp(data['timestamp'][-1] / 1000).day
    yesterday = None
    op = None
    cl = None
    hi = None
    lo = None
    for i in range(len(data['timestamp']) - 1, -1, -1):
        day = datetime.fromtimestamp((data['timestamp'][i] / 1000)).day
        if day != today and yesterday is None:
            yesterday = datetime.fromtimestamp((data['timestamp'][i] / 1000)).day
            cl = float(data["close"][i])
            hi = float(data["high"][i])
            lo = float(data["low"][i])
        elif yesterday is not None and day == yesterday:
            op = float(data["open"][i])
            if float(data["low"][i]) < lo:
                lo = float(data["low"][i])
            if float(data["high"][i]) > hi:
                hi = float(data["high"][i])
        elif yesterday is not None and day != yesterday and day != today:
            #print({"today": today, "yesterday": yesterday, "last_data": day})
            return({"high": hi, "low": lo, "open": op, "close": cl})


def get_24h_candle(data):
    n_candles = 4 * 24 # based on 15m candles
    n_tot = len(data['timestamp'])
    op = None
    cl = None
    hi = None
    lo = None
    if n_tot < n_candles:
        print("too few candles")
        return
    for i in range(n_tot - 1, n_tot - n_candles, -1):
        if i == n_tot - 1:
            cl = float(data["close"][i])
            hi = float(data["high"][i])
            lo = float(data["low"][i])
        else:
            op = float(data["open"][i])
            if float(data["low"][i]) < lo:
                lo = float(data["low"][i])
            if float(data["high"][i]) > hi:
                hi = float(data["high"][i])
    return({"high": hi, "low": lo, "open": op, "close": cl})


def get_1h_candles(times, opens, closes, highs, lows, volumes):
    op = None
    cl = None
    hi = None
    lo = None
    vo = None
    for i in range(len(times)):
        minute = datetime.fromtimestamp((times[i] / 1000)).minute
        if minute == 15:
            op = float(opens[i])
            hi = float(highs[i])
            lo = float(lows[i])
            vo = float(volumes[i])
        elif vo and minute == 0:
            cl = float(closes[i])
            if float(lows[i]) < lo:
                lo = float(lows[i])
            if float(highs[i]) > hi:
                hi = float(highs[i])
            vo += float(volumes[i])
            yield({"high": hi, "low": lo, "open": op, "close": cl, "volume": vo})
            op = None
            cl = None
            hi = None
            lo = None
            vo = None
        elif vo:
            if float(lows[i]) < lo:
                lo = float(lows[i])
            if float(highs[i]) > hi:
                hi = float(highs[i])
            vo += float(volumes[i])


def compute_daily_levels(yesterday_candle):
    if yesterday_candle is None:
        return
    pp = (yesterday_candle[
        "high"] +yesterday_candle["low"] + yesterday_candle[
            "close"]) / 3
    resistance1 = 2 * pp - yesterday_candle["low"]
    support1 = 2 * pp - yesterday_candle["high"]
    resistance2 = pp + (yesterday_candle["high"] - yesterday_candle["low"])
    support2 = pp - (yesterday_candle["high"] -yesterday_candle["low"])
    resistance3 = pp + (2*(yesterday_candle["high"] - yesterday_candle["low"]))
    support3 = pp - (2*(yesterday_candle["high"] - yesterday_candle["low"]))
    return ({
        "pivot": pp,
        "resistance1": resistance1,
        "resistance2": resistance2,
        "resistance3": resistance3,
        "support1": support1,
        "support2": support2,
        "support3": support3
    })

def compute_daily_levels_camarilla(yesterday_candle):
    h_l = (
        yesterday_candle["high"] - yesterday_candle["low"]) * 1.1
    r4 = (h_l / 2) + yesterday_candle["close"]
    r3 = (h_l / 4) + yesterday_candle["close"]
    r2 = (h_l / 6) + yesterday_candle["close"]
    r1 = (h_l / 12) + yesterday_candle["close"]
    s1 = yesterday_candle["close"] - (h_l / 12)
    s2 = yesterday_candle["close"] - (h_l / 6)
    s3 = yesterday_candle["close"] - (h_l / 4)
    s4 = yesterday_candle["close"] - (h_l / 2)
    return ({
        "resistance1": r1,
        "resistance2": r2,
        "resistance3": r3,
        "resistance4": r4,
        "support1": s1,
        "support2": s2,
        "support3": s3,
        "support4": s4
    })


def refill_bnb(state, data, amount, symbol):
    position_manager = PositionManager(
        state, symbol, data["timestamp"][-1])
    balance_quoted = state.balance_quoted
    position_manager.set_value(float(amount))
    low_bnb_amount = 5
    amount_bnb = 0
    #portfolio = query_portfolio()
    if position_manager.has_position:
        amount_bnb = position_manager.position_exposure() * float(data["close"][-1])
    if balance_quoted >= amount and amount_bnb < low_bnb_amount:
        print(
            "Buying BNB, current amount %f" % amount_bnb)
        state.balance_quoted -= position_manager.position_value
        position_manager.open_market(add=True)


def indicator_is_rising(close_prices, touching_band, indicator_values):
    last_touch = None
    values_at_touch = []
    is_rising = None
    i = -1
    try:
        while i > -len(close_prices):
            if close_prices[i] > touching_band[i]:
                values_at_touch.append(indicator_values[i])
                if last_touch is None:
                    last_touch = i
                else:
                    break
            i -= 1
    except IndexError:
        pass
    if len(values_at_touch) >1:
        if values_at_touch[0] > values_at_touch[1]:
            is_rising = True
        else:
            is_rising = False
    return(is_rising, last_touch)

