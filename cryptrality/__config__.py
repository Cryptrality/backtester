import os


def load_config(config_file):
    res = {}
    if os.path.isfile(config_file):
        with open(config_file, "rt") as config_data:
            for line in config_data:
                if line.startswith("#"):
                    continue
                try:
                    key, val = line.split("=")
                    res[key.strip()] = val.strip()
                except ValueError:
                    pass
    return res


working_dir = os.path.abspath(".")


bot_config = os.environ.get("CONFIG_FILE")
if bot_config is None:
    bot_config_cwd = os.path.join(working_dir, "bot.config")
    if os.path.exists(bot_config_cwd) and os.path.isfile(bot_config_cwd):
        bot_config = bot_config_cwd


if bot_config:
    conf_dict = load_config(bot_config)
else:
    conf_dict = {}

env_vars = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "SLIPPAGE",
    "FEES",
    "CACHED_KLINES_PATH",
    "INITIAL_BALANCE",
]
env_dict = {}

for env_var in env_vars:
    env_dict[env_var] = os.environ.get(env_var)
    if env_dict[env_var] is None and env_var in conf_dict:
        env_dict[env_var] = conf_dict[env_var]


if env_dict["SLIPPAGE"]:
    SLIPPAGE = env_dict["SLIPPAGE"]
else:
    SLIPPAGE = 0

if env_dict["FEES"]:
    FEES = env_dict["FEES"]
else:
    FEES = 0.001

if env_dict["CACHED_KLINES_PATH"]:
    CACHED_KLINES_PATH = env_dict["CACHED_KLINES_PATH"]
else:
    CACHED_KLINES_PATH = "cached_klines"

if env_dict["INITIAL_BALANCE"]:
    INITIAL_BALANCE = env_dict["INITIAL_BALANCE"]
else:
    INITIAL_BALANCE = 1000

if env_dict["BINANCE_API_KEY"]:
    BINANCE_API_KEY = env_dict["BINANCE_API_KEY"]
else:
    BINANCE_API_KEY = None

if env_dict["BINANCE_API_SECRET"]:
    BINANCE_API_SECRET = env_dict["BINANCE_API_SECRET"]
else:
    BINANCE_API_SECRET = None


class Api:
    def __init__(self) -> None:
        super().__init__()
        self.BINANCE_API_KEY = BINANCE_API_KEY
        self.BINANCE_API_SECRET = BINANCE_API_SECRET


class Config:
    def __init__(self) -> None:
        super().__init__()
        self.SLIPPAGE = float(SLIPPAGE)
        self.FEES = float(FEES)
        self.CACHED_KLINES_PATH = CACHED_KLINES_PATH
        self.INITIAL_BALANCE = float(INITIAL_BALANCE)
