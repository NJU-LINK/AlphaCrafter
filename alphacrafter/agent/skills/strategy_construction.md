---
name: strategy_construction
description: Generate, backtest, and select the optimal cross-sectional factor-based trading strategy given a factor ensemble and market regime.
---

# Strategy Construction Skill

This skill explains how to generate strategy code, sample hyperparameters conditioned on market regime, run multiple backtest trials, and select the best-performing valid strategy for live execution.

---

## Workflow

### 1. Receive Inputs

Obtain the following from upstream agents:

- **Factor Ensemble** from Screener Agent: list of (factor_id, weight, direction) tuples.
- **Market Regime Assessment** from Screener Agent: trend direction, strength, volatility level, risk level.

If no factor ensemble is received, skip the entire cycle.

### 2. Hyperparameter Sampling

The strategy uses the following tunable hyperparameters. Sample values conditioned on the diagnosed market regime.

| Parameter | Description | Sampling Guidance |
|-----------|-------------|-------------------|
| `N_long` | Number of stocks in long leg | Bull market: favor higher values. Bear/sideways: lower values. |
| `N_short` | Number of stocks in short leg | Bull market: 0 or small. Bear market: higher values. Sideways: balanced with N_long. |
| `beta` | Gross exposure scaling factor | Low risk: 0.6–0.8. Medium risk: 0.3–0.5. High risk: 0.1–0.2. |
| `gamma` | Net exposure tilt | Positive for bull, negative for bear, near-zero for neutral. |

**Maximum number of backtest trials**: 3.

Each trial uses a different hyperparameter sample. Generate distinct samples to explore meaningful variations.

### 3. Portfolio Type Determination

Portfolio type is jointly determined by the factor ensemble specification and market regime:

| Regime | Resulting Portfolio Type |
|--------|--------------------------|
| Bull (strong uptrend) |Long-only (disable short leg) |
| Bear (strong downtrend) | Long-short with short bias |
| Sideways / Choppy | Balanced long-short or market-neutral or Long-only with reduced exposure |

### 4. Position Sizing and Risk Constraints

The following constraints must be enforced in all generated strategy code:

**Exposure Limits by Risk Level**:

| Risk Level | Target Gross Exposure | Net Exposure Range | Per-Name Cap (long) | Per-Name Cap (short) |
|------------|----------------------|--------------------|---------------------|----------------------|
| Low Risk | 80% | ±20% | 10% of total assets | 5% of total assets |
| Medium Risk | 50% | ±15% | 5% of total assets | 3% of total assets |
| High Risk | 20% | ±10% | 2% of total assets | 2% of total assets |

**Important constraints**:

- Gross exposure must not exceed 100% under any circumstance.
- Position ratio should be moderate. Both excessively high (>80%) and excessively low (<15%) gross exposure are undesirable.
- Bull market: long position ratio must exceed short position ratio.
- Bear market: short position ratio must exceed long position ratio.
- Calculate maximum allowable quantity before placing any order. Do not rely on post-trade adjustments or forced liquidations to comply with limits.
- Orders must be in multiples of 100 shares.

**New Position Entry Rules**:

New buys/shorts allowed only when ALL of the following hold:
- Current gross exposure <= target gross exposure.
- Sufficient available cash (for longs) or margin (for shorts).
- Position size respects per-name caps.
- Regime is not High Risk (or only small entries allowed if unavoidable).

If conditions not met, operate in maintenance-only mode (trim only).

### 5. Strategy Code Generation

Generate executable Python strategy code (`strategy.py`) that implements:

1. **Factor combination**: compute composite score as weighted sum of factor values, using weights and directions from the ensemble.
2. **Stock ranking**: rank stocks by composite score, select top `N_long` for long and bottom `N_short` for short.
3. **Position sizing**: apply exposure scaling factor, per-name caps, and cash constraints.
4. **Order generation**: close existing positions not in new signals, then open new positions within capacity limits.
5. **Risk compliance**: enforce all exposure limits and regime-specific rules described in Section 4.

Keep strategy logic simple and interpretable. Avoid unnecessary complexity.

### 6. Backtesting and Selection

For each trial (up to 3):

- Execute the generated strategy code using the backtesting tool.
- Record performance metrics: total return (`r`), Sharpe ratio (`SR`), maximum drawdown (`MDD`).

**Minimum acceptance criteria**:

| Metric | Threshold |
|--------|-----------|
| Total Return | > 8% |
| Sharpe Ratio | > 0.6 |
| Max Drawdown | > -8% |

A trial is valid only if ALL three criteria are satisfied.

**Selection**: Among all valid trials, select the one with the highest Sharpe ratio as the best strategy.

If no trial meets all criteria across 3 attempts, skip live execution and report that no viable strategy was found.

**Important**: Do not overfit to backtest results. If a strategy performs poorly in backtesting, revise or discard it. However, do not endlessly tune to chase marginal improvements.

### 7. Constraint Relaxation

If no trades are generated during backtesting:

- Systematically relax constraints one step at a time (e.g., reduce `N_long`/`N_short`, increase per-name caps, widen net exposure range).
- Re-run backtest after each relaxation step.
- Stop relaxing once trades are generated and criteria are met, or once further relaxation would violate hard risk limits.

## Strategy Validation Criteria

Before live deployment, the selected strategy must satisfy:

| Metric | Threshold |
|--------|-----------|
| Sharpe Ratio | >= 1.0 |
| Max Drawdown | <= 10% |
| Calmar Ratio | >= 1.0 |

## Code Example

Below is a minimal strategy template. Replace <<< and >>> with triple backticks when writing actual code.

```python
# strategy.py
from alphacrafter.sim.utils import get_account_dict, add_order, get_stock_daily_data
import numpy as np
import pandas as pd

# Hyperparameters (set by Trader based on regime)
N_LONG = 10            # number of stocks in long leg
N_SHORT = 0            # number of stocks in short leg (0 for long-only)
BETA = 0.6             # gross exposure scaling factor
WEIGHTING = "equal"    # "equal", "score_weighted", or "cap_weighted"

# Hard risk limits (from regime assessment)
TARGET_GROSS = 0.5
MAX_GROSS = 0.8
NET_EXPOSURE_MIN = -0.15
NET_EXPOSURE_MAX = 0.15
LONG_CAP_PER_NAME = 0.05
SHORT_CAP_PER_NAME = 0.03
MIN_CASH_RESERVE = 0.05

# Factor ensemble
FACTOR_ENSEMBLE = []   # List of {"factor_id": str, "weight": float, "direction": str}

account = get_account_dict()
watchlist = account.get("watch_list", [])
current_positions = {p["symbol"]: p for p in account.get("positions", [])}
available_cash = account.get("available_cash", 0)
total_assets = account.get("total_assets", 0)

max_long_value = total_assets * LONG_CAP_PER_NAME
max_short_value = total_assets * SHORT_CAP_PER_NAME
target_gross_value = total_assets * TARGET_GROSS

# Compute composite factor scores
# Placeholder: replace with actual factor computation from ensemble
scores = {}
for sym in watchlist:
    scores[sym] = 0.0  # weighted sum of factor values

# Rank and select
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
long_candidates = [s for s in ranked if s[1] > 0][:N_LONG]
short_candidates = [s for s in ranked if s[1] < 0][-N_SHORT:] if N_SHORT > 0 else []

long_symbols = {s[0] for s in long_candidates}
short_symbols = {s[0] for s in short_candidates}

# Close positions not in new signals
for sym, pos in current_positions.items():
    qty = pos.get("quantity", 0)
    price = pos.get("current_price", 0)
    if qty > 0 and sym not in long_symbols:
        add_order(symbol=sym, order_type="SELL", price=price, quantity=abs(qty))
    elif qty < 0 and sym not in short_symbols:
        add_order(symbol=sym, order_type="BUY", price=price, quantity=abs(qty))

# Open new long positions
if long_candidates:
    if WEIGHTING == "equal":
        alloc_per_stock = (target_gross_value * BETA) / len(long_candidates)
    else:
        total_score = sum(s[1] for s in long_candidates)
        alloc_per_stock = None  # compute per-stock below

    for sym, score in long_candidates:
        if sym in current_positions and current_positions[sym].get("quantity", 0) > 0:
            continue
        price = get_stock_daily_data(sym, days=1)["close"].iloc[-1]
        if WEIGHTING == "score_weighted" and total_score > 0:
            target_value = (score / total_score) * target_gross_value * BETA
        else:
            target_value = alloc_per_stock
        target_value = min(target_value, max_long_value)
        shares = int(target_value / price / 100) * 100
        if shares > 0 and shares * price <= available_cash:
            add_order(symbol=sym, order_type="BUY", price=price, quantity=shares)
            available_cash -= shares * price

# --- Step 5: Open new short positions (if applicable) ---
if short_candidates:
    alloc_per_stock = (target_gross_value * BETA) / len(short_candidates)
    for sym, score in short_candidates:
        if sym in current_positions and current_positions[sym].get("quantity", 0) < 0:
            continue
        price = get_stock_daily_data(sym, days=1)["close"].iloc[-1]
        target_value = min(alloc_per_stock, max_short_value)
        shares = int(target_value / price / 100) * 100
        if shares > 0:
            add_order(symbol=sym, order_type="SELL", price=price, quantity=shares)
```

## Notes

1. Always close positions first, then open new positions based on remaining available capital.
2. Calculate maximum allowable quantity before placing any order. Do not rely on post-trade adjustments.
3. The position ratio should be moderate. Avoid both excessively high (>80%) and excessively low (<15%) gross exposure.
4. Do not overfit to backtest results. A strategy performing poorly in backtesting should be revised or discarded.