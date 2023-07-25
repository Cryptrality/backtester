# distutils: language=c++

import os
import importlib.machinery
import importlib.util
from inspect import getmembers, isfunction, isclass, isbuiltin
from cryptrality.exchanges import backtest_binance_futures, backtest_binance_spot
from cryptrality.core import scheduler as schedule, State
from cryptrality.logger import SimpleLogger
from cryptrality.__config__ import Config
from datetime import datetime
from cryptrality.plotly import trade_charts

from cryptrality.web import web
from threading import Thread
import pandas as pd
import quantstats as qs
import numpy as np
from argparse import _SubParsersAction
from cryptrality.misc import DefaultHelpParser
from typing import List

conf = Config()

INITIAL_BALANCE = float(conf.INITIAL_BALANCE)


def add_parser(
    subparsers: _SubParsersAction, module_name: str
) -> DefaultHelpParser:
    return subparsers.add_parser(
        module_name,
        add_help=False,
        help=("Test a strategy code with historical data"),
    )


supported_exchanges = ["binance_futures", "binance_spot"]


def backtest(
    subparsers: _SubParsersAction, module_name: str, argv: List[str]
) -> None:

    parser = add_parser(subparsers, module_name)
    parser.add_argument(dest="strategy", help="strategy python source file")
    parser.add_argument(
        "-s",
        "--start",
        dest="start",
        required=True,
        help="Start date in the format of dd-mm-yy",
    )
    parser.add_argument(
        "-e",
        "--end",
        dest="end",
        required=True,
        help="End date in the format of dd-mm-yy",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out",
        help="Output folder",
        default="summary_reports",
    )
    parser.add_argument(
        "--stats",
        dest="stats",
        action="store_true",
        help="Toggle on the report generation",
    )
    parser.add_argument(
        "--plots",
        dest="plots",
        action="store_true",
        help="Toggle on the candlestick chart generation",
    )
    parser.add_argument(
        "--chart_window",
        dest="plot_freq",
        choices=["6h", "24h", "2d", "7d", "1M"],
        help=(
            "If plot is enabled, define the time window for the "
            "candlestick data to be displayed"
        ),
        default="6h",
    )
    parser.add_argument(
        "--exchange",
        dest="exchange",
        default="binance_spot",
        help="Define the exchange to run the backtest",
        choices=supported_exchanges,
    )
    parser.add_argument(
        "--hold_asset",
        dest="hold_asset",
        default="BTC-USD",
        help="Define the asset for the buy and hold comparison. Default BTC-USD",
    )

    args = parser.parse_args(argv)

    dir_out = args.out
    plot_dir = os.path.join(dir_out, "plots")
    backtest_logging = SimpleLogger("bot", dir_out)
    strategy_logging = backtest_logging.add_log("strategy")
    exec_logging = backtest_logging.add_log("execution")

    try:
        os.makedirs(plot_dir)
    except FileExistsError:
        pass

    # file name of the strategy
    file_name = os.path.basename(args.strategy)
    module_name = file_name.replace(".py$", "")
    # load the file as a module
    loader = importlib.machinery.SourceFileLoader(module_name, args.strategy)
    spec = importlib.util.spec_from_loader(module_name, loader)
    my_strategy = importlib.util.module_from_spec(spec)

    Runner = None
    trading_modules = [
        ("backtest_binance_futures", backtest_binance_futures),
        ("backtest_binance_spot", backtest_binance_spot),
    ]
    for trading_module in trading_modules:
        if trading_module[0] == "backtest_%s" % args.exchange:
            Runner = trading_module[1].Runner
            trading_fun = getmembers(trading_module[1], isfunction)
            trading_class = getmembers(trading_module[1], isclass)
            trading_bin = getmembers(trading_module[1], isbuiltin)
            for fun in trading_fun:
                # Add each method/class in the module
                setattr(my_strategy, fun[0], fun[1])
            for cls in trading_class:
                # Add each method/class in the module
                setattr(my_strategy, cls[0], cls[1])
            for bin in trading_bin:
                # Add each method/class in the module
                setattr(my_strategy, bin[0], bin[1])
    setattr(my_strategy, "schedule", schedule)
    setattr(my_strategy, "logger", strategy_logging.log)
    loader.exec_module(my_strategy)
    runner = Runner()
    runner.loggers["main"] = backtest_logging.log
    runner.loggers["exec"] = exec_logging.log
    runner.log_path = backtest_logging.__path__

    state = State()
    runner.setup_data(my_strategy.schedule.all, args.start, args.end, state)
    try:
        my_strategy.initialize(state)
    except AttributeError:
        pass
    try:
        strategy_name = my_strategy.STRATEGY_NAME
    except AttributeError:
        strategy_name = os.path.splitext(os.path.basename(args.strategy))[0]
    # web_runner = web(runner, "production", 8080)
    # web_worker = Thread(target=web_runner.start, daemon=True)
    # web_worker.start()
    runner.run_forever()
    # web_runner.start()
    total_pnl = []
    pnl_str = (
        "%(symbol)s\t%(entry_date)s\t%(entry_price)s"
        "\t%(exit_date)s\t%(exit_price)s\t%(quantity)s\t%(pnl)s\n"
    )
    ord_str = (
        "%(symbol)s\t%(id)s\t%(pos_nr)s\t%(type)s\t%(side)s"
        "\t%(status)s\t%(quantity)s\t%(filled_quantity)s"
        "\t%(close_position)s\t%(limit_price)s\t%(created_time)s"
        "\t%(executed_time)s\t%(fees)s\n"
    )
    header_data = {
        "symbol": "symbol",
        "entry_date": "entry_date",
        "entry_price": "entry_price",
        "exit_date": "exit_date",
        "exit_price": "exit_price",
        "quantity": "quantity",
        "pnl": "pnl",
    }
    ord_header_data = {
        "id": "id",
        "symbol": "symbol",
        "pos_nr": "pos_nr",
        "type": "type",
        "side": "side",
        "status": "status",
        "quantity": "quantity",
        "filled_quantity": "filled_quantity",
        "close_position": "close_position",
        "limit_price": "limit_price",
        "created_time": "created_time",
        "executed_time": "executed_time",
        "fees": "fees",
    }
    out_trades_file = os.path.join(dir_out, "all_trades_by_symbol.tsv")
    out_orders_file = os.path.join(dir_out, "all_orders_by_symbol.tsv")
    with open(out_trades_file, "wt") as out_pnl, open(
        out_orders_file, "wt"
    ) as out_order:
        out_pnl.write(pnl_str % header_data)
        out_order.write(ord_str % ord_header_data)
        for symbol in Runner.positions:
            pos_nr = 0
            for position in Runner.positions[symbol]:
                pos_nr += 1
                total_pnl.append(position.pnl)
                for order in position.orders:
                    ord_data = {
                        "id": order.id,
                        "symbol": order.symbol,
                        "pos_nr": pos_nr,
                        "type": order.type,
                        "side": order.side,
                        "status": order.status,
                        "quantity": order.quantity,
                        "filled_quantity": order.filled_quantity,
                        "close_position": order.close_position,
                        "limit_price": order.limit_price,
                        "created_time": datetime.utcfromtimestamp(
                            order.created_time / 1000
                        ),
                        "executed_time": order.executed_time,
                        "fees": order.fees,
                    }
                    out_order.write(ord_str % ord_data)
                if position.entry_time is None:
                    continue
                pos_data = {
                    "symbol": position.symbol,
                    "entry_date": datetime.utcfromtimestamp(
                        position.entry_time / 1000
                    ),
                    "entry_price": position.price,
                    "exit_date": np.NaN,
                    "exit_price": np.NaN,
                    "quantity": position.quantity,
                    "pnl": np.NaN,
                }
                if position.exit_price:
                    pos_data["exit_price"] = position.exit_price
                    pos_data["exit_date"] = datetime.utcfromtimestamp(
                        position.exit_time / 1000
                    )
                    pos_data["pnl"] = position.pnl
                out_pnl.write(pnl_str % pos_data)

    str_final = (
        "Total PnL: %(total_pnl)f\n"
        "\t\tNumber of winning trades %(n_winning)i / %(n_trades)i"
    )
    print(
        str_final
        % {
            "total_pnl": sum(total_pnl),
            "n_trades": len(total_pnl),
            "n_winning": sum([p > 0 for p in total_pnl]),
        }
    )
    positions = pd.read_csv(out_trades_file, sep="\t", header=0)
    if args.plots:
        trades_g = positions.groupby("symbol")
        for symbol in Runner.plot_data:
            out_plot_data = os.path.join(
                dir_out, "plots", "%s_plot_data.tsv" % symbol
            )
            with open(out_plot_data, "wt") as plot_data:
                plot_keys = list(Runner.plot_data[symbol][0].keys())
                plot_data.write("%s\n" % "\t".join(plot_keys))
                for item in Runner.plot_data[symbol]:
                    plot_data.write(
                        "%s\n"
                        % "\t".join(map(str, [item[k] for k in plot_keys]))
                    )

            df = pd.read_csv(out_plot_data, sep="\t", header=0)
            trades_i = trades_g.get_group(symbol)
            h_name = os.path.join(
                dir_out, "plots", "%s_plot_data.html" % symbol
            )
            trade_charts(
                df.copy(),
                trades_i.copy(),
                h_name,
                symbol,
                Runner.plot_config,
                freq=args.plot_freq,
            )

    if args.stats:
        positions = positions.drop_duplicates()

        symbols = positions["symbol"].unique()
        positions.loc[:, "entry_date"] = pd.to_datetime(
            positions["entry_date"]
        )
        daily_out_html = os.path.join(dir_out, "daily_performance.html")
        daily_out_tsv = os.path.join(dir_out, "daily_performance.tsv")
        daily = (
            positions.resample("d", on="entry_date").sum().dropna(how="all")
        )
        daily["pnl"].to_csv(daily_out_tsv, sep="\t")
        qs.reports.html(
            INITIAL_BALANCE + daily["pnl"].cumsum(),
            args.hold_asset,
            output=daily_out_html,
            title=strategy_name,
        )
        for symbol in symbols:
            out_file = "%s_%s" % (symbol, "stats.html")
            out_html_symbol = os.path.join(dir_out, out_file)
            positions_symbol = positions[positions["symbol"] == symbol]
            daily_symbol = (
                positions_symbol.resample("d", on="entry_date")
                .sum()
                .dropna(how="all")
            )
            qs.reports.html(
                (INITIAL_BALANCE / len(symbols))
                + daily_symbol["pnl"].cumsum(),
                args.hold_asset,
                output=out_html_symbol,
                title="%s - %s" % (symbol, strategy_name),
            )
