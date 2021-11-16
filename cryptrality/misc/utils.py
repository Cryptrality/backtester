from datetime import datetime, timedelta


def round_time(dt=None, round_to=60):
   if dt == None :
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