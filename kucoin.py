"""
KuCoin API client — handles market data and order placement.
KuCoin returns candles as [timestamp, close, open, high, low, volume, turnover]
and returns data newest-first (reverse chronological).
"""
import os
import sys
import time
import hmac
import hashlib
import base64
import json
import logging
import subprocess
import requests

log = logging.getLogger('kucoin_bot')

from config import API_KEY, API_SECRET, API_PASSPHRASE, API_BASE

# ── Tor SOCKS proxy (KuCoin blocks US IPs) ────────────
TOR_READY = False

def _ensure_tor():
    """Start Tor if not running, return True when SOCKS proxy is available."""
    global TOR_READY
    if TOR_READY:
        return True
    try:
        result = subprocess.run(
            ['curl', '--socks5', 'localhost:9050', '-s', '-m', '3',
             'https://api.ipify.org'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            TOR_READY = True
            log.info(f"Tor OK — exit IP: {result.stdout.strip()}")
            return True
    except Exception:
        pass

    log.warning("Tor not running — starting...")
    try:
        subprocess.Popen(
            ['tor', '--defaults-only', '-f', '/etc/tor/torrc'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(20):
            time.sleep(1)
            try:
                r = requests.get('https://api.ipify.org',
                    proxies={'http': 'socks5://localhost:9050',
                             'https': 'socks5://localhost:9050'},
                    timeout=5)
                if r.ok:
                    TOR_READY = True
                    log.info(f"Tor started — exit IP: {r.text.strip()}")
                    return True
            except Exception:
                pass
    except Exception as e:
        log.error(f"Failed to start Tor: {e}")
    return TOR_READY

PROXIES = {
    'http': 'socks5://localhost:9050',
    'https': 'socks5://localhost:9050',
}


def _sign(msg):
    """KuCoin HMAC-SHA256 signing."""
    return base64.b64encode(
        hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()


def _signed_request(method, endpoint, body=None):
    """Authenticated request to KuCoin (via Tor)."""
    _ensure_tor()
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + endpoint
    if body:
        body_str = json.dumps(body)
        msg += body_str
    else:
        body_str = None

    headers = {
        'KC-API-SIGN': _sign(msg),
        'KC-API-TIMESTAMP': ts,
        'KC-API-KEY-VERSION': '2',
        'KC-API-KEY': API_KEY,
        'KC-API-PASSPHRASE': _sign(API_PASSPHRASE),
        'Content-Type': 'application/json',
    }

    url = f'{API_BASE}{endpoint}'
    if method.upper() == 'POST':
        r = requests.post(url, data=body_str, headers=headers,
                          timeout=30, proxies=PROXIES)
    else:
        r = requests.request(method, url, headers=headers,
                             timeout=30, proxies=PROXIES)

    data = r.json()
    if data.get('code') != '200000':
        raise Exception(f"KuCoin {method} {endpoint}: {data.get('msg', data)}")
    return data.get('data', {})


def _public_get(endpoint):
    """Unauthenticated GET (via Tor)."""
    _ensure_tor()
    r = requests.get(f'{API_BASE}{endpoint}', timeout=30, proxies=PROXIES)
    data = r.json()
    if data.get('code') != '200000':
        raise Exception(f"KuCoin GET {endpoint}: {data.get('msg', data)}")
    return data.get('data', {})


class KuCoinClient:
    def __init__(self):
        self.authed = not not (API_KEY and API_SECRET and API_PASSPHRASE)
        if self.authed:
            log.info("KuCoin: authenticated mode")
        else:
            log.warning("KuCoin: read-only (no API credentials)")

    # ── Market Data ───────────────────────────────────

    def get_price(self, symbol='ETH-USDT'):
        """Get current price from latest candle close."""
        klines = self.get_klines(symbol, '5min', 1)
        if klines:
            return klines[-1][4]  # close price
        raise Exception("No klines found")

    def get_klines(self, symbol='ETH-USDT', interval='5min', count=40):
        """Fetch OHLCV candles.

        KuCoin format: [timestamp, close, open, high, low, volume, turnover]
        Returns list of [timestamp, open, high, low, close, volume] — chronologically ordered.
        """
        data = _public_get(f'/api/v1/market/candles?symbol={symbol}&type={interval}&pageSize={count}')

        # KuCoin returns newest-first → reverse for chronological
        data = list(reversed(data))

        # Convert to standard OHLCV: [ts, open, high, low, close, volume]
        result = []
        for c in data:
            result.append([
                float(c[0]),   # timestamp
                float(c[2]),   # open
                float(c[3]),   # high
                float(c[4]),   # low
                float(c[1]),   # close
                float(c[5]),   # volume
            ])
        return result

    # ── Account ───────────────────────────────────────

    def get_balance(self, currency='USDT'):
        if not self.authed:
            return None
        data = _signed_request('GET', f'/api/v1/accounts?currency={currency}')
        for acc in data:
            if acc.get('currency') == currency:
                return {
                    'free': float(acc.get('available', 0)),
                    'locked': float(acc.get('freeze', 0)),
                }
        return {'free': 0, 'locked': 0}

    def get_all_balances(self):
        if not self.authed:
            return {}
        data = _signed_request('GET', '/api/v1/accounts')
        result = {}
        for acc in data:
            free = float(acc.get('available', 0))
            if free > 0:
                result[acc['currency']] = {
                    'free': free,
                    'locked': float(acc.get('freeze', 0)),
                }
        return result

    # ── Trading ───────────────────────────────────────

    def buy_market(self, symbol, quote_amount):
        """Buy with market order. quote_amount = how much USDT to spend.
        Returns order_id.
        """
        if not self.authed:
            raise Exception("No API credentials")

        body = {
            'clientOid': f'kt_{int(time.time()*1000)}',
            'side': 'buy',
            'symbol': symbol,
            'type': 'market',
            'quoteCurrency': 'USDT',
            'quoteQuantity': str(quote_amount),
        }
        return _signed_request('POST', '/api/v1/orders', body=body)

    def sell_market(self, symbol, base_amount):
        """Sell with market order. base_amount = how many coins to sell.
        Returns order_id.
        """
        if not self.authed:
            raise Exception("No API credentials")

        # Get the base currency from symbol (e.g. ETH-USDT → ETH)
        base = symbol.split('-')[0]

        body = {
            'clientOid': f'kt_{int(time.time()*1000)}',
            'side': 'sell',
            'symbol': symbol,
            'type': 'market',
            'baseCurrency': base,
            'baseQuantity': str(base_amount),
        }
        return _signed_request('POST', '/api/v1/orders', body=body)
