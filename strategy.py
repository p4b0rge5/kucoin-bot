"""
Trend-following strategy — identical to IQ Option bot.
Detects consecutive candles in same direction, bet WITH the trend.
"""
import logging

log = logging.getLogger('kucoin_bot')


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


def get_signal(klines, min_consecutive=2):
    """
    Main signal function.
    Returns: ('buy', strength) | ('sell', strength) | (None, 0)
    Follows trend (same as IQ bot line 149).
    """
    if len(klines) < min_consecutive + 1:
        return None, 0

    consec = find_consecutive(klines, min_consecutive)

    if consec > 0:
        return 'buy', consec
    elif consec < 0:
        return 'sell', abs(consec)
    return None, 0


def signal_label(strength):
    if strength <= 2:
        return "weak"
    elif strength <= 5:
        return "medium"
    elif strength <= 10:
        return "strong"
    return "very strong"
