"""
KuCoin Trend Trader — Configuration
Same strategy as IQ Option bot: consecutive candle trend + martingale.
"""
import os

# ── Exchange ──────────────────────────────────────────
EXCHANGE = 'kucoin'
API_BASE = 'https://api.kucoin.com'

# API credentials (KuCoin: Settings → API Keys → create with Spot + Wallet)
API_KEY = os.getenv('KUCOIN_API_KEY', '')
API_SECRET = os.getenv('KUCOIN_API_SECRET', '')
API_PASSPHRASE = os.getenv('KUCOIN_API_PASSPHRASE', '')

# ── Trading Pairs (KuCoin format with hyphen) ────────
SYMBOLS = ['ETH-USDT', 'BTC-USDT']
DEFAULT_SYMBOL = 'ETH-USDT'

# ── Strategy (same as IQ bot) ────────────────────────
CANDLE_INTERVAL = '5min'
CANDLE_COUNT = 40
CONSECUTIVE = 2              # 2+ consecutive candles → signal

TRADE_USD = 20               # Per trade in USDT

# Martingale (same as IQ bot)
MARTINGALE_MAX = 3            # $20 → $40 → $80
MARTINGALE_MULT = 2

# TP/SL
TAKE_PROFIT_PCT = 1.5        # Close at +1.5%
STOP_LOSS_PCT = -1.0         # Close at -1.0%

# Limits
MAX_DAILY_TRADES = 50
DAILY_STOP_LOSS = -50.0
DAILY_TAKE_PROFIT = 50.0

# Timing
POLL_SECONDS = 10
COOLDOWN_SECONDS = 120       # Same as IQ bot

# ── Files ─────────────────────────────────────────────
STATE_FILE = '/opt/baal-agent/workspace/kucoin-bot/bot_state.json'
LOG_FILE = '/opt/baal-agent/workspace/kucoin-bot/logs/kucoin_bot.log'
