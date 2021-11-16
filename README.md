# backtester


For the time being only Binance is supported, and the keys
are required to fetch (very few) info from the exchange


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
