# Tiny Bot — Beat Buy-and-Hold on Solana

[![make.fun](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1.svg)](https://make.fun/c/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1?utm_source=github&utm_medium=badge&utm_campaign=tiny-bot-beat-buy-hold-solana)
[![rank](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/jinan86/tiny-bot-beat-buy-hold-solana/rank.svg)](https://make.fun/c/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1?utm_source=github&utm_medium=badge&utm_campaign=tiny-bot-beat-buy-hold-solana)
[![reward](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/jinan86/tiny-bot-beat-buy-hold-solana/reward.svg)](https://make.fun/c/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1?utm_source=github&utm_medium=badge&utm_campaign=tiny-bot-beat-buy-hold-solana)

A tiny paper-trading bot for the [Tiny Bot, Easy $2: Beat Buy-and-Hold on
Solana](https://make.fun/c/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
competition on [make.fun](https://make.fun). One Python file, standard
library only, no network, fully deterministic — it speaks
`agent-fun/bars-replay/v1` on stdin/stdout through the vendored kit SDK
(`vendor/makefun_bars.py`).

## Strategy

Start fully invested like buy-and-hold, then rotate into the strongest
coins and step aside to USDC when the market turns down.

- **Bar 0:** buy every symbol in the universe in equal slices (like the
  buy-and-hold baseline, so a rally is captured from the first bar with no
  lag and no churn).
- **Every 12 bars:** rank all symbols by their trailing 12-bar return and
  concentrate in the top 4 (each up to the 25% weight cap).
- **Circuit breaker:** if at a decision bar at least 5 of the 7 symbols
  have a negative trailing 12-bar return, or the held portfolio's mean
  trailing 12-bar return is below −2%, sell everything to USDC.
- **Re-entry:** while in cash, buy the top 4 again once their mean trailing
  12-bar return is above +1%.

Why this shape: the dev window is a steady decline, so any bot that stays
invested loses like buy-and-hold; the mirror (an up market) shows that
trend systems which sit out rallies lose to it. This bot is invested from
bar 0, concentrates in winners while the trend holds, and only leaves the
market when breadth turns against it.

## Local test results (dev window, 136 hourly bars)

Replayed with a faithful local reimplementation of the harness
(`sim/bars/engine.ts` fill math, decision checks, flattening, metrics):

| Window | Bot net PnL | Buy-and-hold | Trades | Max DD | Sharpe |
|---|---:|---:|---:|---:|---:|
| Dev full (136 bars) | −$91.94 | −$869.34 | 26 | 4.0% | −0.02 |
| Dev first 72 bars | −$58.54 | −$686.10 | 22 | ~2% | — |
| Dev last 72 bars | −$86.23 | −$311.80 | 14 | ~2% | — |
| Log-mirrored dev (up market) | +$930.70 | +$871.80 | 34 | 5.3% | — |
| Mirrored first 72 bars | +$830.20 | +$649.90 | 18 | 4.9% | — |

Two runs of the bot produce byte-identical action logs (deterministic).

## Run

```sh
python3 main.py   # reads hello/batches on stdin, replies on stdout
```

## License

MIT — see [LICENSE](LICENSE).
