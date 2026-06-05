"""
Grid Trading Strategy.
Creates symmetric buy/sell levels around the current price.
"""
import logging

log = logging.getLogger('kucoin_bot')


def build_grid(current_price, levels=6, spread_pct=0.8, centre_pct=0):
    """
    Build grid levels centered on current_price.

    Each level has a BUY price (lower) and a SELL price (upper).
    Level 0 (lowest) buys at price - spread*levels/2.
    Top level sells at price + spread*levels/2.

    Returns list of dicts:
    [
      {'level': 0, 'buy_price': 1700.50, 'sell_price': 1714.33, 'active': False},
      {'level': 1, 'buy_price': 1707.60, 'sell_price': 1721.43, 'active': False},
      ...
    ]
    """
    center = current_price * (1 + centre_pct / 100)
    half_spread = spread_pct / 100 / 2  # per-level half-spread

    grid = []
    for i in range(levels):
        # Each level is spaced by spread_pct from the next
        mid = center + (i - (levels - 1) / 2) * (spread_pct / 100) * current_price
        buy_price = mid - (spread_pct / 100 * current_price / 2)
        sell_price = mid + (spread_pct / 100 * current_price / 2)

        grid.append({
            'level': i,
            'buy_price': round(buy_price, 2),
            'sell_price': round(sell_price, 2),
            'bought': False,      # True when we bought at this level
            'active': True,
        })

    # Sort by buy_price ascending (lowest grid = biggest discount)
    grid.sort(key=lambda g: g['buy_price'])
    return grid


def check_grid_fills(grid, current_price, min_fill_pct=0.15):
    """
    Check which grid levels the current price has crossed.

    Returns (buys, sells) — lists of grid levels to buy/sell.
    A buy fires when price drops TO/BELLOW a buy_price.
    Only the NEAREST unclosed level fires per tick to avoid overbuying.
    A sell fires when price rises TO/ABOVE a sell_price (and was previously bought).
    """
    buys = []
    sells = []
    threshold = min_fill_pct / 100

    candidate_buys = []

    for g in grid:
        if not g['active']:
            continue

        if not g['bought']:
            # Fire buy when price is at or below buy_price
            if current_price <= g['buy_price']:
                candidate_buys.append(g)
        else:
            # Already bought — check if price hit sell target
            if current_price >= g['sell_price']:
                sells.append(g)

    # Only buy the NEAREST level (highest buy_price ≤ current_price)
    # This prevents buying all levels at once when price crashed
    if candidate_buys:
        nearest = min(candidate_buys, key=lambda g: g['buy_price'])
        # Only if price is within reasonable range of this level
        if current_price >= nearest['buy_price'] * (1 - 0.01):
            buys.append(nearest)

    return buys, sells


def calc_profit_pct(buy_price, sell_price):
    """Net profit % from a grid buy→sell, excluding fees."""
    if buy_price == 0:
        return 0
    return (sell_price - buy_price) / buy_price * 100


def grid_summary(grid, current_price):
    """Compact one-line summary for logging."""
    parts = []
    for g in grid:
        if not g['active']:
            parts.append(f"█{g['level']}")
        elif g['bought']:
            parts.append(f"●{g['level']}")  # filled buy, waiting sell
        else:
            parts.append(f"○{g['level']}")  # open
    return f"[{' '.join(parts)}] @ ${current_price:.2f}"
