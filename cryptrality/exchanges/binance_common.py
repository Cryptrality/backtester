from datetime import datetime, timedelta, timezone
from cryptrality.misc import str_to_minutes


order_status_msg_to_enum = {
    'NEW': 2,
    'PARTIALLY_FILLED': 3,
    'FILLED': 4,
    'CANCELED': 5,
    'EXPIRED': 6,
    'NEW_INSURANCE': 1,
    'NEW_ADL': 1
}

def list_to_klines(item, symbol, period_str):
    '''
    read the data from the CSV (split by ',') from historical
    data and return kline formatted as in the live data stream
    '''
    period_delta = timedelta(
        minutes = str_to_minutes(period_str))
    open_time = datetime.utcfromtimestamp(int(item[0]) / 1000)
    close_time = open_time + period_delta
    event_ts = int(close_time.replace(tzinfo=timezone.utc).timestamp() * 1000)
    kline = {'E': event_ts,
        'e': 'kline',
        'k': {'B': '0',
            'L': item[11],
            'Q': item[9],
            'T': int(item[6]),
            'V': item[10],
            'c': item[4],
            'f': item[11],
            'h': item[2],
            'i': period_str,
            'l': item[3],
            'n': int(item[8]),
            'o': item[1],
            'q': item[7],
            's': symbol,
            't': int(item[0]),
            'v': item[5],
            'x': True},
        's': symbol}
    return kline

def get_step_size_futures(client, symbol):
    '''
    API call to get futures exchange info and return the step
    size of the asset. This is used in turn to round the trade
    amount to comply with the exchange accepted number of digits
    for the give symbol
    '''
    futures_info = client.futures_exchange_info()
    step_size = None
    price_precision = None
    for s in  futures_info['symbols']:
        if s['symbol'] == symbol:
            for filter in s['filters']:
                if filter['filterType'] == 'LOT_SIZE':
                    step_size = float(filter['stepSize'])
                if filter['filterType'] == 'PRICE_FILTER':
                    price_precision = float(filter['tickSize'])
    return (step_size, price_precision)



def get_step_size_spot(client, symbol):
    '''
    API call to get futures exchange info and return the step
    size of the asset. This is used in turn to round the trade
    amount to comply with the exchange accepted number of digits
    for the give symbol
    '''
    spot_info = client.get_exchange_info()
    step_size = None
    price_precision = None
    for s in  spot_info['symbols']:
        if s['symbol'] == symbol:
            for filter in s['filters']:
                if filter['filterType'] == 'LOT_SIZE':
                    step_size = float(filter['stepSize'])
                if filter['filterType'] == 'PRICE_FILTER':
                    price_precision = float(filter['tickSize'])
    return (step_size, price_precision)