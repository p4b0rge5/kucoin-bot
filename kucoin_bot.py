#!/usr/bin/env python3
"""
KuCoin Trend Trader — Same strategy as IQ Option bot.
Follow trend: 2+ consecutive 5min candles → buy WITH streak
Martingale: $20 → $40 → $80 with signal revalidation
"""

import time
import sys
import json
import shutil
import logging
from datetime import datetime

sys.path.insert(0, '/opt/baal-agent/workspace/kucoin-bot')

from config import (
    SYMBOLS, TRADE_USD, CANDLE_INTERVAL, CANDLE_COUNT,
    CONSECUTIVE, POLL_SECONDS, COOLDOWN_SECONDS,
    MAX_DAILY_TRADES, DAILY_STOP_LOSS, DAILY_TAKE_PROFIT,
    TAKE_PROFIT_PCT, STOP_LOSS_PCT, STATE_FILE, LOG_FILE,
    MARTINGALE_MAX, MARTINGALE_MULT,
)
from strategy import get_signal, signal_label
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
        self.cooldowns = {}
        self.pending = {}
        self.open_positions = {}

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

def in_cooldown(symbol):
    return time.time() < s.cooldowns.get(symbol, 0)

def set_cooldown(symbol):
    s.cooldowns[symbol] = time.time() + COOLDOWN_SECONDS

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

def record_trade(symbol, direction, amount, won, net):
    s.trades += 1
    s.daily_trades += 1
    s.pnl += net
    s.daily_pnl += net
    if won:
        s.wins += 1
    else:
        s.losses += 1

    label = "WON" if won else "LOST"
    log.info(f"  ✅ {label} {symbol} {direction} ${amount} PnL ${net:+.2f} | Total ${s.pnl:+.2f}")

    s.log.append({
        't': now_str(), 'a': symbol, 'd': direction,
        '$': amount, 'win': won, 'pnl': round(net, 2)
    })

# ── Martingale Controlado (same as IQ bot) ───────────
def martingale_loop(ku, symbol, direction):
    """
    Martingale with signal revalidation at each step:
    - Before each retry, recheck signal
    - If signal changed or weakened → abort
    - If signal confirms same direction with strength ≥ min → continue
    """
    for step in range(2, MARTINGALE_MAX + 1):
        if not limits_ok():
            return

        amount = TRADE_USD * (MARTINGALE_MULT ** (step - 1))

        log.info(f"  🔁 Martingale step {step}: revalidating signal...")
        time.sleep(5)

        try:
            klines = ku.get_klines(symbol, CANDLE_INTERVAL, CANDLE_COUNT)
            new_sig, new_strength = get_signal(klines, CONSECUTIVE)

            if new_sig is None or new_sig != direction:
                log.info(f"  ⛔ Signal changed (got: {new_sig}/{new_strength}), aborting martingale")
                set_cooldown(symbol)
                return

            if new_strength < CONSECUTIVE:
                log.info(f"  ⛔ Signal weak ({new_strength} < {CONSECUTIVE}), aborting martingale")
                set_cooldown(symbol)
                return

            log.info(f"  ✅ Signal confirmed: {new_sig.upper()} strength={new_strength} → step {step}: ${amount}")

            won, net = execute_trade(ku, symbol, direction, amount, step)
            if won:
                log.info(f"  ✅ Martingale recovered at step {step}!")
                return
        except Exception as e:
            log.error(f"  ❌ Martingale step {step} error: {e}")
            set_cooldown(symbol)
            return

    log.warning(f"  ⛔ Martingale exhausted")

# ── Execute a single trade ───────────────────────────
def execute_trade(ku, symbol, direction, amount, mg_step=0):
    try:
        price = ku.get_price(symbol)

        if direction == 'buy':
            result = ku.buy_market(symbol, amount)
            base_amount = amount / price
        else:
            if symbol in s.open_positions:
                close_position(ku, symbol)
                return True, 0
            else:
                log.info(f"  ⚠️ Sell signal but no position — skipping")
                return False, 0

        s.open_positions[symbol] = {
            'order_id': result,
            'amount_usd': amount,
            'amount_base': base_amount,
            'entry_price': price,
            'direction': 'buy',
            'ts': time.time(),
        }

        label = f"Trade #{s.trades + 1}" if mg_step == 0 else f"Martingale x{mg_step}"
        log.info(f"  🎯 {label}: {symbol} {direction.upper()} ${amount} @ ${price:.2f}")

        time.sleep(3)
        won, net = check_and_close(ku, symbol)
        record_trade(symbol, direction, amount, won, net)
        return won, net

    except Exception as e:
        log.error(f"  ❌ Trade error: {e}")
        return False, -amount

# ── Check open position for TP/SL ────────────────────
def check_and_close(ku, symbol):
    pos = s.open_positions.get(symbol)
    if not pos:
        return False, -TRADE_USD

    for _ in range(20):
        try:
            current = ku.get_price(symbol)
            pct = (current - pos['entry_price']) / pos['entry_price'] * 100

            if pct >= TAKE_PROFIT_PCT:
                close_position(ku, symbol)
                return True, pos.get('realized_pnl', TRADE_USD * 0.85)
            elif pct <= STOP_LOSS_PCT:
                close_position(ku, symbol)
                return False, pos.get('realized_pnl', -pos['amount_usd'])
        except:
            pass
        time.sleep(5)

    close_position(ku, symbol)
    return False, -pos['amount_usd']

# ── Close position ───────────────────────────────────
def close_position(ku, symbol):
    pos = s.open_positions.pop(symbol, None)
    if not pos:
        return

    try:
        current = ku.get_price(symbol)
        pnl = (current - pos['entry_price']) * pos['amount_base']
        pos['realized_pnl'] = pnl

        base = symbol.split('-')[0]
        result = ku.sell_market(symbol, pos['amount_base'])
        log.info(f"  ✅ Closed: {symbol} at ${current:.2f} PnL ${pnl:+.2f}")
    except Exception as e:
        log.error(f"  ❌ close error: {e}")
    s.save()

# ── Check all open positions ─────────────────────────
def monitor_positions(ku):
    for symbol in list(s.open_positions.keys()):
        pos = s.open_positions[symbol]
        try:
            current = ku.get_price(symbol)
            pct = (current - pos['entry_price']) / pos['entry_price'] * 100

            if pct >= TAKE_PROFIT_PCT:
                log.info(f"  🎯 TP hit: {symbol} +{pct:.2f}%")
                close_position(ku, symbol)
            elif pct <= STOP_LOSS_PCT:
                log.info(f"  🛑 SL hit: {symbol} {pct:.2f}%")
                close_position(ku, symbol)
        except Exception as e:
            log.error(f"  ❌ monitor {symbol}: {e}")

# ── Main ─────────────────────────────────────────────
def main():
    global direction

    ku = KuCoinClient()

    log.info("=" * 60)
    mode = "LIVE" if ku.authed else "PAPER"
    log.info(f"🤖 KuCoin Trend Trader — {mode}")
    log.info(f"   Strategy: {CONSECUTIVE}+ consecutive {CANDLE_INTERVAL} → follow trend")
    log.info(f"   Pairs: {SYMBOLS} | Trade: ${TRADE_USD}")
    log.info(f"   Martingale: {MARTINGALE_MAX} steps (${TRADE_USD}→${TRADE_USD*MARTINGALE_MULT}→...)")
    log.info(f"   TP: {TAKE_PROFIT_PCT}% | SL: {STOP_LOSS_PCT}% | Cooldown: {COOLDOWN_SECONDS}s")
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
        else:
            # Detect pre-existing ETH balance as sellable position
            for symbol in SYMBOLS:
                base = symbol.split('-')[0]
                try:
                    bal = ku.get_balance(base)
                    if bal and bal['free'] > 0:
                        price = ku.get_price(symbol)
                        s.open_positions[symbol] = {
                            'order_id': 'pre-existing',
                            'amount_usd': bal['free'] * price,
                            'amount_base': bal['free'],
                            'entry_price': price,
                            'direction': 'sell',
                            'ts': time.time(),
                            'source': 'pre-existing',
                        }
                        log.info(f"  📦 {symbol}: {bal['free']:.6f} {base} ≈ ${bal['free']*price:.2f} (pre-existing, sell-ready)")
                except Exception as e:
                    log.warning(f"  ⚠️ Could not load {base} balance: {e}")

    session_start = datetime.now()
    heartbeat = 0

    while True:
        try:
            s.reset_daily()

            if s.open_positions:
                monitor_positions(ku)

            if not limits_ok():
                log.info("🛑 Daily limits reached — waiting...")
                time.sleep(60)
                continue

            for symbol in SYMBOLS:
                if in_cooldown(symbol):
                    continue

                try:
                    klines = ku.get_klines(symbol, CANDLE_INTERVAL, CANDLE_COUNT)
                    price = klines[-1][4] if klines else 0
                    sig, strength = get_signal(klines, CONSECUTIVE)
                    label = signal_label(strength) if sig else "—"

                    log.info(
                        f"⏰ {now_str()} | {symbol} ${price:.2f} | "
                        f"sig={sig or '—':4s} {label:12s} ({strength})"
                    )

                    if sig and limits_ok():
                        if sig == 'buy':
                            direction = sig
                            if ku.authed:
                                won, _ = execute_trade(ku, symbol, 'buy', TRADE_USD, 0)
                                if not won:
                                    time.sleep(5)
                                    martingale_loop(ku, symbol, 'buy')
                                set_cooldown(symbol)
                            else:
                                log.info(f"  📋 [PAPER] would buy ${TRADE_USD} @ ${price:.2f}")
                                import random
                                won = random.random() > 0.45
                                net = TRADE_USD * 0.85 if won else -TRADE_USD
                                record_trade(symbol, 'buy', TRADE_USD, won, net)
                        else:
                            if symbol in s.open_positions:
                                pos = s.open_positions[symbol]
                                # For pre-existing positions, check actual balance before selling
                                base = symbol.split('-')[0]
                                if pos.get('source') == 'pre-existing':
                                    try:
                                        bal = ku.get_balance(base)
                                        current = ku.get_price(symbol)
                                        if bal and bal['free'] > 0:
                                            # Sell only TRADE_USD worth, keep the rest
                                            sell_amount = TRADE_USD / current
                                            if sell_amount > bal['free']:
                                                sell_amount = bal['free']
                                            amount_usd = sell_amount * current
                                            log.info(f"  🎯 Sell pre-existing: {symbol} {sell_amount:.6f} {base} ≈ ${amount_usd:.2f}")
                                            result = ku.sell_market(symbol, sell_amount)
                                            pnl = (current - pos['entry_price']) * sell_amount
                                            record_trade(symbol, 'sell', amount_usd, pnl > 0, pnl)
                                            # Update position with remaining balance
                                            bal['free'] -= sell_amount
                                            if bal['free'] <= 0.000001:
                                                del s.open_positions[symbol]
                                                log.info(f"  📦 All {base} sold — position cleared")
                                            else:
                                                pos['amount_base'] = bal['free']
                                                pos['amount_usd'] = bal['free'] * current
                                                pos['entry_price'] = current
                                                log.info(f"  📦 Remaining: {bal['free']:.6f} {base} ≈ ${bal['free']*current:.2f}")
                                            set_cooldown(symbol)
                                            s.save()
                                            continue
                                        else:
                                            log.info(f"  ⚠️ {base} balance empty — sell skipped")
                                    except Exception as e:
                                        log.error(f"  ❌ Sell error: {e}")
                                else:
                                    close_position(ku, symbol)
                            else:
                                log.info(f"  ℹ️ Sell signal, no open position — skipping")

                except Exception as e:
                    log.error(f"  💥 {symbol}: {e}")

            heartbeat += 1
            if heartbeat % 6 == 0:
                mins = (datetime.now() - session_start).total_seconds() / 60
                wr = s.wins / s.trades * 100 if s.trades else 0
                log.info(
                    f"💓 #{s.trades} W:{s.wins} L:{s.losses} "
                    f"WR:{wr:.0f}% Daily ${s.daily_pnl:+.2f} "
                    f"Total ${s.pnl:+.2f} Open:{len(s.open_positions)} {mins:.0f}min"
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
