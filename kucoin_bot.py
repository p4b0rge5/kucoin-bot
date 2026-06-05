#!/usr/bin/env python3
"""
KuCoin Grid Trader — Automatic buy/sell grid levels.
Buys when price drops, sells when it rises. Profits from sideways movement.
"""

import time
import sys
import json
import shutil
import logging
from datetime import datetime

sys.path.insert(0, '/opt/baal-agent/workspace/kucoin-bot')

from config import (
    SYMBOLS, GRID_LEVELS, GRID_SPREAD_PCT, GRID_TRADE_USD,
    GRID_MIN_PCT, POLL_SECONDS, GRID_COOLDOWN,
    MAX_DAILY_TRADES, DAILY_STOP_LOSS, DAILY_TAKE_PROFIT,
    REBALANCE_INTERVAL, REBALANCE_THRESHOLD,
    STATE_FILE, LOG_FILE,
)
from strategy import build_grid, check_grid_fills, calc_profit_pct, grid_summary
from kucoin import KuCoinClient

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode='a'),
    ]
)
log = logging.getLogger('kucoin_bot')

# ── State ────────────────────────────────────────────
class State:
    def __init__(self):
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.pnl = 0.0
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_date = None
        self.log = []
        self.cooldowns = {}         # {level: timestamp}
        self.grid_levels = []       # Current grid state
        self.last_rebalance = 0    # timestamp

    def reset_daily(self):
        today = datetime.now().strftime('%Y-%m-%d')
        if self.last_date != today:
            if self.last_date:
                log.info(f"📅 New day (was {self.last_date}). Reset counters.")
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_date = today

    def save(self):
        try:
            data = {
                'trades': self.trades, 'wins': self.wins, 'losses': self.losses,
                'pnl': round(self.pnl, 2), 'daily_trades': self.daily_trades,
                'daily_pnl': round(self.daily_pnl, 2),
                'log': self.log[-200:],
                'grid_levels': self.grid_levels,
                'last_rebalance': self.last_rebalance,
                'saved_at': datetime.now().isoformat(),
            }
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            shutil.move(tmp, STATE_FILE)
        except Exception as e:
            log.error(f"💾 save error: {e}")

    def load(self):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            self.trades = data.get('trades', 0)
            self.wins = data.get('wins', 0)
            self.losses = data.get('losses', 0)
            self.pnl = data.get('pnl', 0.0)
            self.daily_trades = data.get('daily_trades', 0)
            self.daily_pnl = data.get('daily_pnl', 0.0)
            self.log = data.get('log', [])
            self.grid_levels = data.get('grid_levels', [])
            self.last_rebalance = data.get('last_rebalance', 0)
            self.last_date = datetime.now().strftime('%Y-%m-%d')
            if self.trades:
                log.info(f"📂 Loaded: {self.trades} trades, PnL ${self.pnl:+.2f}")
            return True
        except FileNotFoundError:
            return False

s = State()
s.load()
s.reset_daily()

# ── Helpers ──────────────────────────────────────────
def now_str():
    return datetime.now().strftime('%H:%M:%S')

def in_cooldown(level):
    return time.time() < s.cooldowns.get(level, 0)

def set_cooldown(level):
    s.cooldowns[level] = time.time() + GRID_COOLDOWN

def limits_ok():
    if s.daily_trades >= MAX_DAILY_TRADES:
        log.warning(f"⛔ Max daily trades ({MAX_DAILY_TRADES}) reached")
        return False
    if s.daily_pnl <= DAILY_STOP_LOSS:
        log.warning(f"⛔ Daily stop-loss hit (${s.daily_pnl:.2f})")
        return False
    if s.daily_pnl >= DAILY_TAKE_PROFIT:
        log.info(f"🎯 Daily take-profit reached (${s.daily_pnl:.2f})")
        return False
    return True

def record_trade(symbol, direction, amount, buy_price, sell_price, won, net):
    s.trades += 1
    s.daily_trades += 1
    s.pnl += net
    s.daily_pnl += net
    if won:
        s.wins += 1
    else:
        s.losses += 1

    label = "WON" if won else "LOST"
    profit_pct = calc_profit_pct(buy_price, sell_price) if buy_price else 0
    log.info(
        f"  ✅ {label} {symbol} {direction} ${amount:.2f} "
        f"buy@${buy_price:.2f} sell@${sell_price:.2f} "
        f"(+{profit_pct:.1f}%) PnL ${net:+.2f} | Total ${s.pnl:+.2f}"
    )

    s.log.append({
        't': now_str(), 'a': symbol, 'd': direction,
        '$': amount, 'bp': buy_price, 'sp': sell_price,
        'win': won, 'pnl': round(net, 2)
    })

# ── Grid Initialization ──────────────────────────────
def init_grid(ku, symbol):
    """Build or rebuild grid levels around current price."""
    price = ku.get_price(symbol)
    grid = build_grid(price, GRID_LEVELS, GRID_SPREAD_PCT)
    s.grid_levels = grid
    s.last_rebalance = time.time()

    log.info("=" * 60)
    log.info(f"📐 Grid initialized at ${price:.2f} — {GRID_LEVELS} levels, {GRID_SPREAD_PCT}% spread")
    for g in grid:
        profit = calc_profit_pct(g['buy_price'], g['sell_price'])
        marker = "🔵" if not g['bought'] else "🔴"
        log.info(
            f"  {marker} L{g['level']:d}: buy ${g['buy_price']:.2f} → sell ${g['sell_price']:.2f} "
            f"(+{profit:.1f}%, ${GRID_TRADE_USD})"
        )
    log.info("=" * 60)
    return grid

# ── Execute Grid Order ───────────────────────────────
def execute_grid_buy(ku, symbol, level):
    """Buy at grid level."""
    if not limits_ok():
        return
    if in_cooldown(level['level']):
        log.info(f"  ⏳ Cooldown on L{level['level']} — skipping")
        return

    try:
        price = ku.get_price(symbol)
        result = ku.buy_market(symbol, GRID_TRADE_USD)

        level['bought'] = True
        level['buy_actual'] = price
        level['buy_ts'] = time.time()

        # Get actual fill amount from balance
        time.sleep(2)
        base = symbol.split('-')[0]
        bal = ku.get_balance(base)
        eth_bought = bal['free'] if bal else GRID_TRADE_USD / price

        log.info(
            f"  🟢 BUY L{level['level']}: ${GRID_TRADE_USD:.2f} @ ${price:.2f} "
            f"→ {eth_bought:.6f} {base}"
        )

        set_cooldown(level['level'])
        s.save()
    except Exception as e:
        log.error(f"  ❌ Buy L{level['level']} error: {e}")
        level['bought'] = False

def execute_grid_sell(ku, symbol, level):
    """Sell what was bought at this grid level."""
    if not limits_ok():
        return
    if in_cooldown(level['level']):
        log.info(f"  ⏳ Cooldown on L{level['level']} — skipping")
        return

    try:
        price = ku.get_price(symbol)
        base = symbol.split('-')[0]

        # Check actual balance to sell
        bal = ku.get_balance(base)
        if not bal or bal['free'] <= 0:
            log.info(f"  ⚠️ No {base} to sell at L{level['level']}")
            return

        # Sell amount = what was bought (estimated from trade_usd / buy_price)
        buy_price = level.get('buy_actual', level['buy_price'])
        estimated_base = GRID_TRADE_USD / buy_price

        # Sell the actual available amount (up to estimated)
        sell_amount = round(min(estimated_base, bal['free']), 7)
        if sell_amount <= 0.0000001:
            log.info(f"  ⚠️ Too small to sell L{level['level']}: {sell_amount}")
            return

        result = ku.sell_market(symbol, sell_amount)

        # Calculate PnL
        pnl = (price - buy_price) * sell_amount
        amount_usd = sell_amount * price
        profit_pct = calc_profit_pct(buy_price, price)
        won = pnl > 0

        record_trade(symbol, 'sell', amount_usd, buy_price, price, won, pnl)

        level['bought'] = False
        if 'buy_actual' in level:
            del level['buy_actual']
        if 'buy_ts' in level:
            del level['buy_ts']

        log.info(
            f"  🟡 SELL L{level['level']}: {sell_amount:.6f} {base} @ ${price:.2f} "
            f"PnL ${pnl:+.2f} (+{profit_pct:.1f}%)"
        )

        set_cooldown(level['level'])
        s.save()
    except Exception as e:
        log.error(f"  ❌ Sell L{level['level']} error: {e}")

# ── Main Loop ────────────────────────────────────────
def main():
    ku = KuCoinClient()

    log.info("=" * 60)
    mode = "LIVE" if ku.authed else "PAPER"
    log.info(f"🤖 KuCoin Grid Trader — {mode}")
    log.info(f"   Grid: {GRID_LEVELS} levels × {GRID_SPREAD_PCT}% spread")
    log.info(f"   Trade/level: ${GRID_TRADE_USD}")
    log.info(f"   Cooldown: {GRID_COOLDOWN}s | Poll: {POLL_SECONDS}s")
    log.info(f"   Daily limits: {MAX_DAILY_TRADES} trades | SL ${DAILY_STOP_LOSS} | TP ${DAILY_TAKE_PROFIT}")
    log.info("=" * 60)

    if ku.authed:
        try:
            bals = ku.get_all_balances()
            for cur, bal in bals.items():
                log.info(f"  💰 {cur}: {bal['free']:.6f}")
            if not bals:
                log.warning("⚠️ Empty wallet — paper trading only")
        except Exception as e:
            log.error(f"❌ Auth failed: {e}")
            ku.authed = False

    session_start = datetime.now()
    heartbeat = 0

    for symbol in SYMBOLS:
        init_grid(ku, symbol)

    while True:
        try:
            s.reset_daily()

            for symbol in SYMBOLS:
                if not limits_ok():
                    continue

                try:
                    price = ku.get_price(symbol)

                    # Rebalance grid if price drifted too far
                    if time.time() - s.last_rebalance > REBALANCE_INTERVAL:
                        if s.grid_levels:
                            center = s.grid_levels[len(s.grid_levels)//2]['buy_price']
                            if abs(price - center) / center * 100 > REBALANCE_THRESHOLD:
                                log.info(f"🔄 Price drifted {abs(price - center)/center*100:.1f}% — rebuilding grid")
                                init_grid(ku, symbol)
                        else:
                            init_grid(ku, symbol)

                    if not s.grid_levels:
                        init_grid(ku, symbol)

                    # Show grid status
                    summary = grid_summary(s.grid_levels, price)
                    log.info(f"⏰ {now_str()} | {symbol} ${price:.2f} | {summary}")

                    # Check for fills
                    buys, sells = check_grid_fills(s.grid_levels, price, GRID_MIN_PCT)

                    for level in sells:
                        if ku.authed:
                            execute_grid_sell(ku, symbol, level)
                        else:
                            buy_price = level.get('buy_actual', level['buy_price'])
                            net = GRID_TRADE_USD * calc_profit_pct(buy_price, level['sell_price']) / 100
                            record_trade(symbol, 'sell', GRID_TRADE_USD, buy_price, level['sell_price'], True, net)
                            level['bought'] = False

                    for level in buys:
                        if ku.authed:
                            execute_grid_buy(ku, symbol, level)
                        else:
                            log.info(f"  📋 [PAPER] Buy L{level['level']} at ${level['buy_price']:.2f}")
                            level['bought'] = True

                except Exception as e:
                    log.error(f"  💥 {symbol}: {e}")

            heartbeat += 1
            if heartbeat % 12 == 0:
                mins = (datetime.now() - session_start).total_seconds() / 60
                wr = s.wins / s.trades * 100 if s.trades else 0
                active = sum(1 for g in s.grid_levels if g.get('bought')) if s.grid_levels else 0
                log.info(
                    f"💓 #{s.trades} W:{s.wins} L:{s.losses} "
                    f"WR:{wr:.0f}% Daily ${s.daily_pnl:+.2f} "
                    f"Total ${s.pnl:+.2f} Grid:{active}/{len(s.grid_levels)} filled | {mins:.0f}min"
                )
                s.save()

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log.info("🛑 Stopped by user")
            break
        except Exception as e:
            log.error(f"💥 Loop error: {e}")
            time.sleep(30)

    mins = (datetime.now() - session_start).total_seconds() / 60
    wr = s.wins / s.trades * 100 if s.trades else 0
    log.info("=" * 60)
    log.info(f"📋 Final: {mins:.0f}min | {s.trades} trades W:{s.wins} L:{s.losses} WR:{wr:.0f}%")
    log.info(f"   PnL: ${s.pnl:+.2f} | Daily: ${s.daily_pnl:+.2f}")
    log.info("=" * 60)
    s.save()

if __name__ == '__main__':
    main()
