---
name: factor_mining
description: Discover, validate, and persist alpha factors through script-driven research workflows in the market.
---

# Factor Mining Skill Documentation

This skill explains how to research, evaluate, and persist factors using a script-driven workflow.

## Workflow

### 1. Generate Research Script

- Write Python scripts into: `scripts/<miner_id>_<YYYYMMDD>_<description>.py`
- Script purposes include:
  - Computing factor values across the watchlist
  - Performing IC analysis
  - Testing factor logic variations
  - Exploring combinations or transformations of existing factors
- Validate only ONE idea (i.e. single type of factor) per script
- **Performance note**: The watchlist contains hundreds of stocks (CSI300/S&P500 constituents). Scripts must be very efficient

### 2. Execute Script

- Use the `shell` tool to run the script
- Execution results (stdout and stderr) are returned for interpretation
- Print outputs at a fine-grained level for clear visibility. Avoid silent failures or overly aggregated summaries that hide.

### 3. Validate Factor

Based on script output, evaluate:

- **Information Coefficient (IC)**: correlation between factor value and forward return
- **ICIR**: IC stability over time
- **Turnover**: signal change frequency
- **Coverage**: percentage of watchlist with valid factor values
- **Concentration**: measure of factor value distribution across stocks
  - Identify if factor is broadly applicable or selective
  - A factor with low coverage but high effectiveness on targeted stocks can still be valuable
- **Decay**: half-life of predictive power

### 4. Persist Factor

To view the current factor library, use the shell tool:

```bash
ls factors/
```

Save factor definition and validation results to:

```bash
factors/<miner_id>_<YYYYMMDD>_<factor_id>.json
```

**Note**: Always keep a list of currently effective factors in the memory summary. For fundamental factors that may be temporarily ineffective but are considered market pillars (e.g., momentum factors), conduct periodic re-validation to assess regime-dependent decay or potential re-emergence of predictive power.

## Factor Format

Each persisted factor JSON should contain:

| Field | Description |
|-------|-------------|
| `factor_id` | Unique identifier, e.g., "momentum_20d" |
| `factor_name` | Human-readable name |
| `version` | Version number or timestamp |
| `calculation.expression` | Mathematical definition, e.g., "1 - close/rolling_max(close,60)" |
| `calculation.description` | Plain-language explanation |
| `dependencies` | Required data fields (close, volume, etc.) |
| `parameters` | Configurable parameters with defaults |
| `validation.metrics` | IC, ICIR, turnover, coverage, concentration, decay |
| `validation.period` | Time range of validation |
| `validation.status` | EFFECTIVE or DEPRECATED |
| `validation.regime_notes` | Market conditions during validation |
| `tags` | Categories (momentum, value, quality, etc.) |
| `last_validated` | Timestamp of most recent validation |