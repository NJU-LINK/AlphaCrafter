---
name: factor_screening
description: Select and assemble effective factors from the factor library using regime-aware methodology and optional script validation.
---

# Factor Screening Skill (Simplified)


## Workflow

### 1. Load Factor Library

Retrieve validated factors from persistence store (`factors/*.json`) or Miner Agent

To view the current factor library, use the shell tool:

```bash
ls factors/
```

### 2. Market Data Retrieval & Regime Assessment

Obtain recent market information to evaluate current market conditions for regime-aware factor selection.

### 3. Factor Preprocessing & Alignment

- Standardize factor exposures (rank normalization or Z-score)
- Handle missing values (neutral assignment: median or zero)
- Align factor directions to common return prediction convention (e.g., higher value -> higher expected return)
- Winsorize extreme exposures

### 4. Factor Correlation & Redundancy Management

- Compute pairwise correlation matrix across selected factors
- Identify highly correlated clusters (correlation > 0.7)
- Apply one of the following:
  - **Cluster pruning**: retain highest ICIR factor per cluster
  - **Orthogonalization**: regress out correlated components
  - **Diversification constraint**: cap weight for any correlated group

### 5. Multi-Factor Ensemble Construction

Choose based on regime stability and data quality:

#### Score-Based Weighting
- Normalize performance metrics (ICIR, hit rate, stability) → factor scores
- Assign weights proportional to scores
- Penalize high turnover or low coverage

#### Regime-Aware Tiers
- Primary (weight ~0.5–0.7): regime-favored factors
- Secondary (weight ~0.2–0.4): supporting factors
- Tertiary (weight ~0.0–0.1): hedge or diversifiers