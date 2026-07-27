---
name: factor_mining
description: Discover, validate, and persist alpha factors through script-driven research workflows in the market.
---

# Factor Mining Skill Documentation

This skill explains how to research, evaluate, and persist factors using a script-driven workflow. Factors are validated across multiple horizons with strict metric thresholds, and existing factors undergo periodic re-validation.

## Workflow

### 1. Generate Research Script

- Write Python scripts into: `scripts/<miner_id>_<YYYYMMDD>_<description>.py`
- Script purposes include:
  - Computing factor values across the watchlist
  - Performing IC analysis across multiple horizons
  - Testing factor logic variations
  - Exploring combinations or transformations of existing factors
- Validate only ONE idea (single factor type) per script
- **Performance note**: The watchlist contains hundreds of stocks (CSI300/S&P500 constituents). Scripts must be efficient.
- **Data sufficiency**: Some stocks have limited history (recent IPOs). Filter out stocks with `len(df) < min_required_days` before computation.

### 2. Execute Script

- Use the `shell` tool to run the script: `python scripts/<script_name>.py`
- Execution results (stdout and stderr) are returned for interpretation.
- Print outputs at a fine-grained level for clear visibility. Avoid silent failures or overly aggregated summaries.

### 3. Validate Factor

For each candidate factor, compute metrics across required evaluation horizons:

| Horizon | Forward Return | Min IC | Min RankIC | Min ICIR | Min RankICIR | Min Hit Ratio | Min Coverage | Max Turnover |
|---------|---------------|--------|------------|----------|--------------|---------------|--------------|--------------|
| 1 day | 1-day fwd return | > 0.015 | > 0.015 | > 0.2 | > 0.2 | > 0.6 or < 0.4 | > 0.9 | < 0.4 |
| 5 day | 5-day fwd return | > 0.025 | > 0.025 | > 0.25 | > 0.25 | > 0.6 or < 0.4 | > 0.9 | < 0.4 |

**Metrics definitions** (computed per-horizon as time-series averages):

- **IC (Information Coefficient)**: mean of cross-sectional Pearson correlation between factor values and forward returns over time
- **Rank IC**: mean of cross-sectional Spearman rank correlation between factor values and forward returns over time
- **ICIR**: mean(IC_t) / std(IC_t)
- **Rank ICIR**: mean(RankIC_t) / std(RankIC_t)
- **Hit Ratio**: proportion of periods where RankIC_t > 0
- **Coverage**: mean proportion of universe with valid (non-NA) factor values over time
- **Turnover**: mean L1 distance of cross-sectional ranks between consecutive periods, normalized by universe size

**Pass condition**: ALL metrics across BOTH horizons must satisfy their respective thresholds. Record `last_validated` timestamp on success.

### 4. Persist Factor

To view the current factor library:

```bash
  ls factors/
```
Save validated factor to:

```bash
  factors/<miner_id>_<YYYYMMDD>_<factor_id>.json
```
### 5. Periodic Re-validation

- Re-validation interval: **90 days**
- For each existing factor where `current_time - last_validated >= 90 days`, re-run full validation.
- On success: update `last_validated` timestamp.
- On failure: mark factor as DEPRECATED; rename file with `_deprecated` suffix.

---

## Factor JSON Format

Each persisted factor JSON should contain:

| Field | Description |
|-------|-------------|
| `factor_id` | Unique identifier, e.g., "momentum_20d" |
| `factor_name` | Human-readable name |
| `version` | Version number or timestamp |
| `calculation.expression` | Mathematical definition |
| `calculation.description` | Plain-language explanation |
| `dependencies` | Required data fields (close, volume, etc.) |
| `parameters` | Configurable parameters with defaults |
| `validation.metrics.1-day` | Metrics for 1-day horizon |
| `validation.metrics.5-day` | Metrics for 5-day horizon |
| `validation.status` | `EFFECTIVE` or `DEPRECATED` |
| `validation.regime_notes` | Market conditions during validation |
| `tags` | Categories (momentum, value, quality, etc.) |
| `last_validated` | ISO timestamp of most recent validation |

---

## Code Example

```python
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from alphacrafter.sim.utils import get_account_dict, get_stock_daily_data

# Configuration
HORIZONS = [1, 5]                 # evaluation horizons in days
MIN_REQUIRED_DAYS = 252           # minimum history length
UNIVERSE = get_account_dict()["watch_list"]

# Fetch Data
data = {}
for sym in UNIVERSE:
    df = get_stock_daily_data(sym, days=MIN_REQUIRED_DAYS)
    if df is not None and len(df) >= MIN_REQUIRED_DAYS:
        data[sym] = df.set_index("date")["close"].to_frame("close")
        data[sym]["return_1d"] = data[sym]["close"].pct_change(1).shift(-1)
        data[sym]["return_5d"] = data[sym]["close"].pct_change(5).shift(-5)

# Factor Definition
# Example: 20-day momentum (replace with your factor logic)
for sym in data:
    data[sym]["factor"] = data[sym]["close"] / data[sym]["close"].rolling(20).mean() - 1

# Validation
for h in HORIZONS:
    ic_list, rank_ic_list = [], []
    coverage_list, turnover_list = [], []
    prev_rank = None

    # Align all symbols to common date index
    dates = sorted(set().union(*[d.index for d in data.values()]))
    for t in dates:
        factor_vals, fwd_returns = [], []
        valid_syms = []
        for sym, d in data.items():
            if t in d.index:
                f = d.loc[t, "factor"]
                r = d.loc[t, f"return_{h}d"]
                if pd.notna(f) and pd.notna(r):
                    factor_vals.append(f)
                    fwd_returns.append(r)
                    valid_syms.append(sym)

        n_total = len(data)
        n_valid = len(factor_vals)
        coverage_list.append(n_valid / n_total if n_total > 0 else 0.0)

        if n_valid >= 30:  # minimum cross-section size
            ic = np.corrcoef(factor_vals, fwd_returns)[0, 1]
            rank_ic, _ = spearmanr(factor_vals, fwd_returns)
            ic_list.append(ic)
            rank_ic_list.append(rank_ic)

            # Turnover
            curr_rank = pd.Series(factor_vals, index=valid_syms).rank()
            if prev_rank is not None:
                aligned = curr_rank.align(prev_rank, join="inner")
                turnover = np.abs(aligned[0] - aligned[1]).sum() / len(aligned[0])
                turnover_list.append(turnover)
            prev_rank = curr_rank

    # Aggregate metrics
    ic_mean = np.mean(ic_list) if ic_list else 0
    rank_ic_mean = np.mean(rank_ic_list) if rank_ic_list else 0
    icir = ic_mean / np.std(ic_list) if ic_list and np.std(ic_list) > 0 else 0
    rank_icir = rank_ic_mean / np.std(rank_ic_list) if rank_ic_list and np.std(rank_ic_list) > 0 else 0
    hit_ratio = np.mean([1 for v in rank_ic_list if v > 0]) if rank_ic_list else 0
    coverage = np.mean(coverage_list) if coverage_list else 0
    turnover = np.mean(turnover_list) if turnover_list else 0

    print(f"Horizon {h}d: IC={ic_mean:.4f} RankIC={rank_ic_mean:.4f} "
          f"ICIR={icir:.4f} RankICIR={rank_icir:.4f} "
          f"HitRatio={hit_ratio:.4f} Coverage={coverage:.4f} Turnover={turnover:.4f}")
```

## Notes

1. Always check `len(df) >= min_required_days` to exclude stocks with insufficient history.
2. Use at least 30 valid stocks per cross-section for reliable correlation estimates.
3. When encountering bugs, attempt alternative equivalent approaches rather than stubbornly persisting with the problematic method.
4. The factor inventory is dynamic: new factors added upon validation, existing factors deprecated upon failed re-validation.
5. Always keep a summary of currently effective factors in output context. For fundamental factors temporarily ineffective but considered market pillars, conduct periodic re-validation to assess potential re-emergence.