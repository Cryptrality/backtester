import os
import importlib.machinery
import importlib.util
from datetime import datetime
from inspect import getmembers, isfunction, isclass
from cryptrality.exchanges import binance_futures
from cryptrality.core import scheduler as schedule, State
from cryptrality.logger import SimpleLogger
from cryptrality.web import web
from threading import Thread


def add_parser(subparsers, module_name):
    return subparsers.add_parser(
        module_name,
        add_help=False,
        help=("Run a strategy live on the exchangerm"),
    )


def live(subparsers, module_name, argv):
    """Run a strategy live on an exchange"""

    parser = add_parser(subparsers, module_name)
    parser.add_argument(dest="strategy", help="strategy python source file")
    parser.add_argument(
        "--web",
        dest="web",
        action="store_true",
        help="Toggle on the web inspector",
    )
    parser.add_argument(
        "--port",
        dest="web_port",
        default="5050",
        type=int,
        help="Web port to point the inspector (default 5050)",
    )
    parser.add_argument(
        "--user",
        dest="web_user",
        default="alba",
        type=str,
        help="User name to access the inspector (default alba)",
    )
    parser.add_argument(
        "--password",
        dest="web_password",
        default="calidris",
        type=str,
        help="User password to access the inspector (default calidris)",
    )
    args = parser.parse_args(argv)

    # file name of the strategy
    file_name = os.path.basename(args.strategy)
    module_name = file_name.replace(".py", "")
    # load the file as a module
    loader = importlib.machinery.SourceFileLoader(module_name, args.strategy)
    spec = importlib.util.spec_from_loader(module_name, loader)
    my_strategy = importlib.util.module_from_spec(spec)
    now_ts = datetime.utcnow().strftime("%Y_%m_%d_%H_%M")
    dir_out = os.path.join(os.path.dirname(args.strategy), module_name, now_ts)
    bot_logging = SimpleLogger("bot", dir_out)
    strategy_logging = bot_logging.add_log("strategy")
    exec_logging = bot_logging.add_log("execution")
    Runner = None
    trading_modules = [("binance_futures", binance_futures)]
    for trading_module in trading_modules:
        if trading_module[0] == "%s" % "binance_futures":
            Runner = trading_module[1].Runner
            trading_fun = getmembers(trading_module[1], isfunction)
            trading_class = getmembers(trading_module[1], isclass)
            for fun in trading_fun:
                # Add each method/class in the module
                setattr(my_strategy, fun[0], fun[1])
            for cls in trading_class:
                # Add each method/class in the module
                setattr(my_strategy, cls[0], cls[1])

    setattr(my_strategy, "schedule", schedule)
    setattr(my_strategy, "logger", strategy_logging.log)

    loader.exec_module(my_strategy)
    runner = Runner()
    runner.loggers["main"] = bot_logging.log
    runner.loggers["exec"] = exec_logging.log
    runner.log_path = bot_logging.__path__

    state = State()
    try:
        my_strategy.initialize(state)
    except AttributeError:
        pass
    try:
        strategy_name = my_strategy.STRATEGY_NAME
    except AttributeError:
        strategy_name = os.path.splitext(os.path.basename(args.strategy))[0]
    print(
        "Running %(strategy_name)s live on %(exchange)s"
        % {"strategy_name": strategy_name, "exchange": "Binance Futures"}
    )
    runner.setup_data(my_strategy.schedule.all, state)
    if args.web:
        web_runner = web(
            runner,
            mode="production",
            port=args.web_port,
            static_username=args.web_user,
            static_password=args.web_password,
        )
        web_worker = Thread(target=web_runner.start, daemon=True)
        web_worker.start()
    runner.run_forever()
