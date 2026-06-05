"""
Trend-following strategy with volatility filter.
Detects consecutive candles in same direction, bet WITH the trend.
Skips choppy/low-volatility markets to avoid trading noise.
"""
import logging

log = logging.getLogger('kucoin_bot')


def candle_range_pct(candle):
    """Return candle range as % of open price: (high - low) / open * 100"""
    _, o, h, l, _, _ = candle
    return (h - l) / o * 100 if o else 0


def is_volatile_enough(klines, last_n=3, min_range_pct=0.1):
    """
    Check if the last N candles have meaningful range.
    If average range < min_range_pct%, market is too choppy → skip.
    """
    if len(klines) < last_n:
        return True
    ranges = [candle_range_pct(k) for k in klines[-last_n:]]
    avg_range = sum(ranges) / len(ranges)
    return avg_range >= min_range_pct


def find_consecutive(candles, min_n):
    """
    Find streak of consecutive candles in same direction.
    candles: list of [timestamp, open, high, low, close, volume]
    Returns: direction * count if streak >= min_n, else 0
    +N = bullish streak, -N = bearish streak, 0 = no signal
    """
    if len(candles) < min_n + 1:
        return 0

    last = candles[-1]
    o, c = last[1], last[4]

    if c > o:
        direction = 1
    elif c < o:
        direction = -1
    else:
        return 0

    count = 0
    for i in range(len(candles) - 1, -1, -1):
        o2, _, _, _, c2, _ = candles[i]
        dd = 1 if c2 > o2 else (-1 if c2 < o2 else 0)
        if dd == 0 or dd != direction:
            break
        count += 1

    return direction * count if count >= min_n else 0


def get_signal(klines, min_consecutive=3, min_volatility=0.1):
    """
    Main signal function with volatility filter.
    Returns: ('buy', strength) | ('sell', strength) | (None, 0)
    Follows trend. Skips low-volatility chop.
    """
    if len(klines) < min_consecutive + 1:
        return None, 0

    # Volatility filter — don't trade dead markets
    if not is_volatile_enough(klines, last_n=3, min_range_pct=min_volatility):
        return None, 0

    consec = find_consecutive(klines, min_consecutive)

    if consec > 0:
        return 'buy', consec
    elif consec < 0:
        return 'sell', abs(consec)
    return None, 0


def signal_label(strength):
    if strength <= 3:
        return "weak"
    elif strength <= 6:
        return "medium"
    elif strength <= 12:
        return "strong"
    return "very strong"
