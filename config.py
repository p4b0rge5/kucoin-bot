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

# ── Strategy (adaptive candle + volatility filter) ────
CANDLE_INTERVAL = '5min'           # 5min = less noise, stronger signals
CANDLE_COUNT = 48                  # 4 hours of history
CONSECUTIVE = 3                    # 3+ consecutive = higher conviction

TRADE_USD = 3.50                   # Above min, better fee-to-profit ratio

# Martingale
MARTINGALE_MAX = 2
MARTINGALE_MULT = 2

# TP/SL — wider to absorb fees, still realistic
TAKE_PROFIT_PCT = 3.0             # Close at +3% (covers fee 0.2%, net ~2.8%)
STOP_LOSS_PCT = -2.0              # Close at -2% (risk/reward 1.5:1)

# Volatility filter — skip if recent candles are too small
MIN_CANDLE_RANGE_PCT = 0.1        # Skip if latest candle range < 0.1% of price

# Limits (same as IQ bot)
MAX_DAILY_TRADES = 10000
DAILY_STOP_LOSS = -1000
DAILY_TAKE_PROFIT = 1000

# Timing
POLL_SECONDS = 15
COOLDOWN_SECONDS = 300       # 5min — lets the move play out

# ── Files ─────────────────────────────────────────────
STATE_FILE = '/opt/baal-agent/workspace/kucoin-bot/bot_state.json'
LOG_FILE = '/opt/baal-agent/workspace/kucoin-bot/logs/kucoin_bot.log'
