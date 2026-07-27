---
name: factor_screening
description: Select and assemble effective factors from the factor library using regime-aware methodology and script-driven validation.
---

# Factor Screening Skill

This skill explains how to load the factor library, assess market conditions, compute factor suitability scores, apply semantic diversification, and output a weighted factor ensemble. All factor computations use cross-sectional Rank IC over a recent lookback window as the primary selection signal.

## Workflow

### 1. Market Data Retrieval and Regime Assessment

- Use tools to retrieve benchmark index data for trend and volatility assessment.
- Diagnose market regime based on retrieved data.

### 2. Load Factor Library

Retrieve validated factors from persistence store:

```bash
  ls factors/
```

List all `.json` files (excluding `_deprecated`). Each factor record contains detailed information. Only consider factors that are effective. Based on factor filenames, make a preliminary judgment of semantic relevance to the current market regime. Factors clearly irrelevant by name alone can be skipped immediately. For factors whose relevance is uncertain based on filename alone, read the full JSON file to obtain detailed information. Use this detailed information to make a definitive relevance judgment. Skip factors confirmed as irrelevant. All factors that pass or remain uncertain after detailed inspection proceed to suitability scoring.

### 3. Factor Suitability Scoring

Write Python scripts into: `scripts/screener_<YYYYMMDD>_<description>.py`

For each factor in the active library:

1. Compute the factor vector across the current watchlist universe for each of the most recent trading days in the lookback window.
2. For each day in the lookback window, compute the 1-day forward return for each stock.
3. For each day, compute the cross-sectional Spearman rank correlation between factor values and forward returns.
4. Compute the mean Rank IC over the lookback window as the factor's suitability score.

**Parameters**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Lookback window | 10 days | Number of recent trading days for Rank IC averaging |
| Minimum history | 252 days | Minimum trading days required per stock |
| Minimum cross-section | 30 stocks | Minimum valid stocks per day for IC calculation |
| Suitability threshold | 0.02 (absolute) | Minimum absolute mean Rank IC for factor selection |

### 4. Semantic Diversification

- Rank all candidate factors by absolute suitability score in descending order.
- Iteratively select factors:
  - Skip factors with absolute suitability score below the threshold.
  - For each candidate, evaluate its semantic similarity against all already-selected factors.
  - Reject candidates whose semantic similarity to any selected factor exceeds the similarity threshold.
- **Semantic similarity threshold**: 0.8 (scale 0 to 1). Factors with expression-level overlap above this threshold are considered redundant.

### 5. Weight Normalization and Direction Assignment

For each selected factor:

- **Weight**: Absolute suitability score divided by the sum of absolute suitability scores across all selected factors.
- **Direction**: Long if mean Rank IC is positive, short if negative.

Output the final factor ensemble as a list of (factor_id, weight, direction) tuples.

## Code Example

```python
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from alphacrafter.sim.utils import get_account_dict, get_stock_daily_data

# Configuration
LOOKBACK = 10                     # days for Rank IC averaging
MIN_REQUIRED_DAYS = 252           # minimum history per stock
MIN_CROSS_SECTION = 30            # minimum valid stocks per day
SUITABILITY_THRESHOLD = 0.02      # minimum absolute mean Rank IC

# Candidate Factors (pre-filtered by Screener)
CANDIDATES = [
    {"factor_id": "momentum_20d", "expression": "close / close.rolling(20).mean() - 1"},
    {"factor_id": "volatility_10d", "expression": "-close.pct_change(10).std()"},
]

# Fetch Data
universe = get_account_dict()["watch_list"]
data = {}
for sym in universe:
    df = get_stock_daily_data(sym, days=MIN_REQUIRED_DAYS)
    if df is not None and len(df) >= MIN_REQUIRED_DAYS:
        data[sym] = df.set_index("date")["close"].to_frame("close")
        data[sym]["return_1d"] = data[sym]["close"].pct_change(1).shift(-1)

# Evaluate Each Candidate
results = []

for cand in CANDIDATES:
    factor_id = cand["factor_id"]
    expr = cand["expression"]

    # Compute factor values for each stock
    for sym in data:
        close = data[sym]["close"]
        try:
            data[sym]["factor"] = eval(expr)
        except Exception:
            data[sym]["factor"] = np.nan

    # Daily Rank IC over lookback window
    rank_ic_list = []
    dates = sorted(set().union(*[d.index for d in data.values()]))[-LOOKBACK:]

    for t in dates:
        factor_vals, fwd_returns = [], []
        for sym, d in data.items():
            if t in d.index:
                f = d.loc[t, "factor"]
                r = d.loc[t, "return_1d"]
                if pd.notna(f) and pd.notna(r):
                    factor_vals.append(f)
                    fwd_returns.append(r)

        if len(factor_vals) >= MIN_CROSS_SECTION:
            rank_ic, _ = spearmanr(factor_vals, fwd_returns)
            rank_ic_list.append(rank_ic)

    if rank_ic_list:
        mean_rank_ic = np.mean(rank_ic_list)
        results.append({
            "factor_id": factor_id,
            "suitability_score": mean_rank_ic
        })
        print(f"{factor_id}: Mean Rank IC (10d) = {mean_rank_ic:.4f}")
    else:
        print(f"{factor_id}: Insufficient data, skipped")

# Threshold Filtering and Weighting
results = [r for r in results if abs(r["suitability_score"]) >= SUITABILITY_THRESHOLD]
results.sort(key=lambda x: abs(x["suitability_score"]), reverse=True)

total_abs_score = sum(abs(r["suitability_score"]) for r in results)
ensemble = []

for r in results:
    weight = abs(r["suitability_score"]) / total_abs_score if total_abs_score > 0 else 0
    direction = "LONG" if r["suitability_score"] > 0 else "SHORT"
    ensemble.append({
        "factor_id": r["factor_id"],
        "weight": round(weight, 4),
        "direction": direction,
        "suitability_score": round(r["suitability_score"], 4)
    })
    print(f"Selected: {r['factor_id']} | Weight: {weight:.4f} | Direction: {direction}")
```

## Notes

1. The `eval()` call in the example is a placeholder. In practice, parse the factor expression safely or implement a dedicated computation function for each factor type.
2. Always filter out stocks with `len(df) < MIN_REQUIRED_DAYS` to avoid unstable estimates from short histories.
3. Semantic similarity filtering is performed by the LLM based on factor descriptions and expression logic, not by the script itself.
4. If fewer than a minimum viable number of factors pass the threshold, consider skipping the cycle rather than forcing a low-quality ensemble.