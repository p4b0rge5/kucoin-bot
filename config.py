"""
KuCoin Grid Trader — Configuration
Automatic buy-sell grid levels for sideways markets.
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

# ── Trading Pair ─────────────────────────────────────
SYMBOLS = ['ETH-USDT']
DEFAULT_SYMBOL = 'ETH-USDT'

# ── Grid Configuration ───────────────────────────────
GRID_CENTRE_PCT = 0          # Grid centered on current price (0%)
GRID_LEVELS = 6              # Number of buy-sell pairs (6 levels = 12 price lines)
GRID_SPREAD_PCT = 0.8        # Each grid level spread ±0.8% from center
GRID_TRADE_USD = 2.20        # Amount per grid order (buy $2.20, sell $2.20+profit)
GRID_MIN_PCT = 0.15          # Min % move to trigger order (avoids fee loss)

# ── Grid Range ───────────────────────────────────────
# Grid auto-calculates: center_price ± (levels * spread / 2)
# Example at $1730 with 6 levels × 0.8%: $1730 ± 2.4% → ~$1688-$1772

# ── Timing ───────────────────────────────────────────
POLL_SECONDS = 15            # Check every 15s
GRID_COOLDOWN = 30           # Cooldown per grid level after fill (seconds)

# ── Rebalance ────────────────────────────────────────
REBALANCE_INTERVAL = 3600    # Recalculate grid levels every hour
REBALANCE_THRESHOLD = 2.0    # Recalculate if price moves >2% from center

# ── Limits ───────────────────────────────────────────
MAX_DAILY_TRADES = 200
DAILY_STOP_LOSS = -50
DAILY_TAKE_PROFIT = 50

# ── Files ────────────────────────────────────────────
STATE_FILE = '/opt/baal-agent/workspace/kucoin-bot/bot_state.json'
LOG_FILE = '/opt/baal-agent/workspace/kucoin-bot/logs/kucoin_bot.log'
