#!/usr/bin/env python3
"""Tiny Bot — beat buy-and-hold on Solana hourly bars.

Strategy: start fully invested like buy-and-hold, then rotate into the
strongest coins and step aside to USDC when the market turns down.

  - Bar 0: buy every symbol in the universe in equal slices (like the
    buy-and-hold baseline, so a rally is captured from the first bar with
    no lag and no churn).
  - Every 12 bars, rank all symbols by their trailing 12-bar return and
    concentrate in the top 4 (each up to the 25% weight cap).
  - Circuit breaker: if at a decision bar at least 5 of the 7 symbols have
    a negative trailing 12-bar return, or the held portfolio's mean
    trailing 12-bar return is below -2%, sell everything to USDC.
  - Re-entry: while in cash, buy the top 4 again once their mean trailing
    12-bar return is above +1%.

Why this shape: the dev window is a steady decline, so any bot that stays
invested loses like buy-and-hold; the mirror (an up market) shows that
trend systems which sit out rallies lose to it. This bot is invested from
bar 0, concentrates in winners while the trend holds, and only leaves the
market when breadth turns against it — so it beats buy-and-hold in both
regimes on the dev window, its sub-windows, and a log-mirrored up market.

Deterministic: no clock, no environment, no randomness. All comparisons
are exact integer / Fraction arithmetic, so two runs produce byte-identical
action logs. Standard library only; speaks agent-fun/bars-replay/v1
through the vendored kit SDK (vendor/makefun_bars.py).
"""

import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

LOOKBACK_BARS = 12          # trailing return window, in bars
DECIDE_EVERY_BARS = 12      # rebalance / regime check cadence
TOP_N = 4                   # symbols held after concentration
BREAKER_RETURN = Fraction(-2, 100)   # portfolio 12-bar return below this -> exit
BREADTH_EXIT = 5            # symbols with negative 12-bar return -> exit
REENTRY_RETURN = Fraction(1, 100)    # top-4 mean 12-bar return above this -> re-enter
MAX_SLIPPAGE_BPS = 100      # 1% past the close an order was decided on
OPEN_SLIPPAGE_BPS = 10_000  # opening buys take whatever the next open does

# Each symbol's closes by batch, in universe order; None before its first bar.
closes = {}
# The next batch seq a decision runs on (first one with a full lookback).
next_decide = LOOKBACK_BARS
# Symbols to top up / buy on the next batch, after sells have filled.
pending_targets = None
# "invested" while holding, "cash" after the breaker fired.
regime = "invested"
# True once the opening buys have gone out.
started = False


def trailing_return(symbol, seq):
    """The symbol's return over LOOKBACK_BARS as an exact Fraction, or None."""
    hist = closes[symbol]
    if seq - LOOKBACK_BARS < 0:
        return None
    now = hist[seq]
    then = hist[seq - LOOKBACK_BARS]
    if now is None or then is None:
        return None
    return Fraction(now, then) - 1


def ranked_returns(state, seq):
    """(symbol, return) pairs with a return, best first; ties keep universe order."""
    universe = [s["symbol"] for s in state.hello["symbols"]]
    pairs = []
    for name in universe:
        r = trailing_return(name, seq)
        if r is not None:
            pairs.append((name, r))
    pairs.sort(key=lambda p: (-p[1], universe.index(p[0])))
    return pairs


def top_up_orders(state, targets):
    """Buy orders bringing each target symbol to an equal TOP_N slice of equity."""
    caps = state.hello["caps"]
    fees = state.hello["fees"]
    equity = state.equity
    per_target = min(equity // TOP_N, caps["max_weight_bps"] * equity // 10_000)
    orders = []
    cash = state.cash
    for symbol in targets:
        held = state.positions.get(symbol)
        value = state.value(symbol, held.qty) if held is not None else 0
        need = per_target - value
        if need >= int(fees["min_notional_quote_units"]) and need <= cash:
            orders.append({
                "side": "buy", "symbol": symbol,
                "notional_quote_units": need,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
                "client_id": "c%d-%s" % (state.seq, symbol),
            })
            cash -= need
    return orders


def on_batch(state, batch):
    global next_decide, pending_targets, regime, started
    seq = state.seq
    for bar in batch["bars"]:
        closes.setdefault(bar["symbol"], []).append(int(bar["c"]))
    for symbol in state.hello["symbols"]:
        name = symbol["symbol"]
        if name not in closes:
            closes[name] = []
        while len(closes[name]) <= seq:
            closes[name].append(None)

    if state.warming_up:
        return []

    if not started:
        started = True
        priced = [s["symbol"] for s in state.hello["symbols"] if state.close(s["symbol"]) is not None]
        if not priced:
            return []
        caps = state.hello["caps"]
        fees = state.hello["fees"]
        per = min(state.cash // len(priced),
                  caps["max_weight_bps"] * state.equity // 10_000)
        if per < int(fees["min_notional_quote_units"]):
            return []
        return [{
            "side": "buy", "symbol": symbol,
            "notional_quote_units": per,
            "max_slippage_bps": OPEN_SLIPPAGE_BPS,
            "client_id": "i-%s" % symbol,
        } for symbol in priced]

    if pending_targets is not None:
        targets = pending_targets
        pending_targets = None
        return top_up_orders(state, targets)

    if seq < next_decide:
        return []
    next_decide = seq + DECIDE_EVERY_BARS

    ranked = ranked_returns(state, seq)
    if not ranked:
        return []
    top = [name for name, _ in ranked[:TOP_N]]
    mean_top = sum(r for _, r in ranked[:TOP_N]) / len(ranked[:TOP_N])
    negative = sum(1 for _, r in ranked if r < 0)

    if regime == "cash":
        if mean_top > REENTRY_RETURN:
            regime = "invested"
            caps = state.hello["caps"]
            fees = state.hello["fees"]
            per = min(state.cash // len(top),
                      caps["max_weight_bps"] * state.equity // 10_000)
            if per < int(fees["min_notional_quote_units"]):
                return []
            return [{
                "side": "buy", "symbol": symbol,
                "notional_quote_units": per,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
                "client_id": "r%d-%s" % (seq, symbol),
            } for symbol in top]
        return []

    held_names = list(state.positions)
    basis = held_names if held_names else [name for name, _ in ranked]
    port_return = sum(trailing_return(name, seq) for name in basis) / len(basis)
    if port_return < BREAKER_RETURN or negative >= BREADTH_EXIT:
        regime = "cash"
        return [{
            "side": "sell", "symbol": name,
            "qty": state.positions[name].qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
            "client_id": "x%d-%s" % (seq, name),
        } for name in held_names]

    sells = [{
        "side": "sell", "symbol": name,
        "qty": state.positions[name].qty,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
        "client_id": "x%d-%s" % (seq, name),
    } for name in held_names if name not in top]
    if sells:
        # The sells' proceeds land at the next open and never fund a buy of
        # this reply, so the top-ups go out on the next batch.
        pending_targets = top
        return sells

    return top_up_orders(state, top)


makefun_bars.run(on_batch)
