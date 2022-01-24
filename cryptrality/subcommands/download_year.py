from io import BytesIO
from zipfile import ZipFile
from urllib.request import urlopen
import urllib
import os
from cryptrality.__config__ import Config
from cryptrality.misc import xopen


config = Config()

supported_exchanges = [
    'binance_futures', 'binance_spot']

if config.CACHED_KLINES_PATH:
    CACHED_KLINES_PATH = config.CACHED_KLINES_PATH
else:
    CACHED_KLINES_PATH = 'cached_klines'

def add_parser(subparsers, module_name):
    return subparsers.add_parser(
        module_name, add_help=False,
        help=('Download yearly historical data'))


def download_year(subparsers, module_name, argv):

    parser = add_parser(subparsers, module_name)
    parser.add_argument(dest='symbol',
        help='Symbol to download, eg ETHUSDT')
    parser.add_argument('-k', '--kline', dest='k', required=True, type=str,
        help='Granularity string, eg 1m 5m 1h.')
    parser.add_argument('-y', '--year', dest='year', required=True, type=int, nargs='*',
        help='Year of the data to download. full year needed eg 2020')
    parser.add_argument('-e', '--exchange', dest='exchange',
        choices=supported_exchanges,
        default='binance_spot', help='Supported exchanges')
    args = parser.parse_args(argv)



    # or: requests.get(url).content

    symbol = args.symbol
    years = list(map(str, args.year))

    period_1 = args.k

    exchange = args.exchange

    if exchange.startswith('binance'):
        year_short_start = years[0][-2:]
        year_short_end = years[-1][-2:]
        months = ["%.2d" %i for i in range(1,13)]
        if exchange == 'binance_futures':
            url="https://data.binance.vision/data/futures/um/monthly/klines/%(symbol)s/%(period)s/%(symbol)s-%(period)s-%(year)s-%(month)s.zip"
            file_out_1 = 'binance_futures_%s_%s_1_1_%s_31_12_%s.csv.gz' % (
                symbol, period_1, year_short_start, year_short_end)
        elif exchange == 'binance_spot':
            url="https://data.binance.vision/data/spot/monthly/klines/%(symbol)s/%(period)s/%(symbol)s-%(period)s-%(year)s-%(month)s.zip"
            file_out_1 = 'binance_spot_%s_%s_1_1_%s_31_12_%s.csv.gz' % (
                symbol, period_1, year_short_start, year_short_end)

        file_out = os.path.join(CACHED_KLINES_PATH, file_out_1)
        with xopen(file_out, 'wt') as file_1:
            for year in years:
                for month in months:
                    url_month = url % {'symbol': symbol, 'period': period_1, 'month': month, 'year': year}
                    print(url_month)
                    try:
                        resp = urlopen(url_month)
                        zipfile = ZipFile(BytesIO(resp.read()))
                        for line in zipfile.open(zipfile.namelist()[0]).readlines():
                            file_1.write(line.decode('utf-8'))
                    except urllib.error.HTTPError:
                        pass
