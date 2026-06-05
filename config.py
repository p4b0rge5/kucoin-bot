"""
KuCoin Trend Trader — Configuration
Same strategy as IQ Option bot: consecutive candle trend + martingale.
"""
import os
import json

# ── Exchange ──────────────────────────────────────────
EXCHANGE = 'kucoin'
API_BASE = 'https://api.kucoin.com'

# API credentials — loaded from credentials file
_CREDS_FILE = os.path.join(os.path.dirname(__file__), '.kucoin_creds.json')
try:
    _creds = json.load(open(_CREDS_FILE))
except Exception:
    _creds = {}

API_KEY = _creds.get('key', os.getenv('KUCOIN_API_KEY', ''))
API_SECRET = _creds.get('secret', os.getenv('KUCOIN_API_SECRET', ''))
API_PASSPHRASE = _creds.get('passphrase', os.getenv('KUCOIN_API_PASSPHRASE', ''))

# ── Trading Pairs (KuCoin format with hyphen) ────────
SYMBOLS = ['ETH-USDT']
DEFAULT_SYMBOL = 'ETH-USDT'

# ── Strategy (same as IQ bot) ────────────────────────
CANDLE_INTERVAL = '1min'
CANDLE_COUNT = 40
CONSECUTIVE = 2              # 2+ consecutive candles → signal

TRADE_USD = 1.80              # Min order size ETH-USDT ~$1.76, use $1.80

# Martingale (same as IQ bot)
MARTINGALE_MAX = 2            # $1.80 → $3.60
MARTINGALE_MULT = 2

# TP/SL
TAKE_PROFIT_PCT = 1.5        # Close at +1.5%
STOP_LOSS_PCT = -1.0         # Close at -1.0%

# Limits (same as IQ bot)
MAX_DAILY_TRADES = 10000
DAILY_STOP_LOSS = -1000
DAILY_TAKE_PROFIT = 1000

# Timing
POLL_SECONDS = 10
COOLDOWN_SECONDS = 120       # Same as IQ bot

# ── Files ─────────────────────────────────────────────
STATE_FILE = '/opt/baal-agent/workspace/kucoin-bot/bot_state.json'
LOG_FILE = '/opt/baal-agent/workspace/kucoin-bot/logs/kucoin_bot.log'
