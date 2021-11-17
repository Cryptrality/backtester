# backtester


For the time being only Binance is supported, and the keys
are required to fetch (very few) info from the exchange

The syntax of the strategy is quite different from trality,
but hopefully there will be further developments to mimic
Trality API to have minimal edit required to run the backtesting
locally


### Install

It might be possible to install the package as a module,
but the setup script had not being carefully maintained, so
it's easier to run the the module as a local folder.

    python3 -m venv venv

    venv/bin/pip install -r requirements.txt



### Run a backtest


    BINANCE_API_KEY="xxxx" BINANCE_API_SECRET="xxxx" venv/bin/python \
        strategy_example.py --start 1-11-21 --end 16-11-21 \
        --out strategy_trades.csv

### Inspect performance

    python3 scripts/print_profits.py strategy_trades.csv


### Without Binance API:


It's possible to run the backstesting even omitting the Binance API keys.
The limitation is that the data need to be store already in the cache folder
and an arbitraty step size (the digits step in wich is possible to buyt the asset)
will be used.


#### Fetch the yearly candle for a given symbol:


    python3 scripts/download_yearly_data.py BTCUSDT 2020 15m
    mkdir -p cached_klines
    mv BTCUSDT_15m_1_1_20_31_12_20.csv cached_klines


#### Run withouth API KEYS

    venv/bin/python \
        strategy_example.py --start 1-1-20 --end 31-12-20 \
        --out strategy_trades.csv 


