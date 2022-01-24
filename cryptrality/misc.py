import os
import sys
import gzip
import argparse
from datetime import datetime, timedelta, timezone


def round_time(dt=None, round_to=60):
    if dt is None:
        dt = datetime.utcnow()
    seconds = (dt.replace() - dt.min).seconds
    rounding = (seconds + round_to / 2) // round_to * round_to
    return dt + timedelta(0, rounding - seconds, -dt.microsecond)


def str_to_minutes(period_str):
    unit = period_str[-1]
    value = int(period_str[:-1])
    convert_unit = {
        'm': 1,
        'h': 60,
        'd': 60 * 24,
        'w': 60 * 24 * 7,
    }
    return value * convert_unit[unit]


def xopen(filename, mode='r'):
    '''
    Replacement for the "open" function that can also open
    files that have been compressed with gzip. If the filename ends with .gz,
    the file is opened with gzip.open(). If it doesn't, the regular open()
    is used. If the filename is '-', standard output (mode 'w') or input
    (mode 'r') is returned.
    '''
    assert isinstance(filename, str)
    if filename == '-':
        return sys.stdin if 'r' in mode else sys.stdout
    if filename.endswith('.gz'):
        return gzip.open(filename, mode)
    else:
        return open(filename, mode)


def package_modules(package):
    pathname = package.__path__[0]
    return set(['.'.join([package.__name__, os.path.splitext(module)[0]])
                for module in os.listdir(pathname)
                if module.endswith('.py') and
                not module.startswith('__init__')])


def get_modules(parent, subparsers, progs):
    '''
    return the list of modules in the program module
    '''
    mods = package_modules(parent)
    for mod in sorted(mods):
        try:
            __import__(mod)
            mod_name = mod.split('.')[-1]
            m = getattr(parent, mod_name)
            m.add_parser(subparsers, mod_name)
            progs[mod_name] = getattr(m, mod_name)
        except AttributeError as err:
            raise(err)
            pass
    return progs


class SubcommandHelpFormatter(argparse.RawDescriptionHelpFormatter):

    def _format_action(self, action):
        parts = super(argparse.RawDescriptionHelpFormatter,
                      self)._format_action(action)
        if action.nargs == argparse.PARSER:
            parts = "\n".join(parts.split("\n")[1:])
        return parts


class DefaultHelpParser(argparse.ArgumentParser):

    def error(self, message):
        import sys
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(2)

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

def candle_close_timestamp(timestamp, interval):
    '''
    Compute the UTC closing time of a candle given its interval string
    (eg 1m, 15m, 1h) and the opening UTC timestamp
    '''
    date_open = datetime.utcfromtimestamp(
        timestamp / 1000)
    offset = timedelta(minutes=str_to_minutes(interval))
    date = date_open + offset
    return int(
        date.replace(tzinfo=timezone.utc).timestamp() * 1000)