import requests
from config import MARGIN_PERCENT

def get_exchange_rate():
    url = "https://v6.exchangerate-api.com/v6/b7dae8052fd7953bf7c7f66e/latest/IDR"
    res = requests.get(url)
    data = res.json()
    rate = data["conversion_rates"]["TRY"]
    return rate

def convert_idr_to_try(nominal_rp):
    rate = get_exchange_rate()
    margin = (MARGIN_PERCENT / 100) * nominal_rp
    bersih = nominal_rp - margin
    return int(bersih * get_exchange_rate())

def convert_try_to_idr(nominal_try):
    rate = get_exchange_rate()
    idr = nominal_try / rate
    margin = (MARGIN_PERCENT / 100) * idr
    return int(idr - margin)