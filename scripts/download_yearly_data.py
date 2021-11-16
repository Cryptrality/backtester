from io import BytesIO
from zipfile import ZipFile
from urllib.request import urlopen
import urllib
import sys
# or: requests.get(url).content

symbol=sys.argv[1]
year=sys.argv[2]

period_1=sys.argv[3]

months = ("%.2d" %i for i in range(1,13))
url="https://data.binance.vision/data/spot/monthly/klines/%(symbol)s/%(period)s/%(symbol)s-%(period)s-2021-%(month)s.zip"

year_short = year[-2:]

file_out_1 = '%s_%s_1_1_%s_31_12_%s.csv' % (
    symbol, period_1, year_short, year_short) 

print(file_out_1)

with open(file_out_1, 'wt') as file_1:
    for month in months:
        url_month = url % {'symbol': symbol, 'period': period_1, 'month': month}
        print(url_month)
        try:
            resp = urlopen(url_month)
            zipfile = ZipFile(BytesIO(resp.read()))
            for line in zipfile.open(zipfile.namelist()[0]).readlines():
                file_1.write(line.decode('utf-8'))
        except urllib.error.HTTPError:
            pass
