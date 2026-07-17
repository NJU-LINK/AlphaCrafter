---
name: position_management
description: Given current market regime and factor context, determine gross exposure, net exposure, cash allocation, and position limits for long-short portfolios.
---

# Position Management Skill Document

## 1. Get Market Regime Assessment

Get current market assessment:

- **Overall trend**: Bull market (uptrend), Bear market (downtrend), Sideways/Range-bound
- **Trend strength**: Weak, Moderate, Strong (using MA slope, ADX, or consecutive direction days)
- **Volatility regime**: Low, Normal, High
- **Liquidity condition**: Normal, Tight, Stressed
- **Correlation regime**: Low, Normal, High (stocks move together vs disperse)
- **Sector rotation pace**: Slow, Normal, Fast
- **Breadth**: Wide, Normal, Narrow
- **Trend/Mean-Reversion tendency**: Trending, Mixed, Mean-Reverting
- **Sentiment regime**: Neutral, Optimistic, Pessimistic, Extreme

## 2. Set Gross & Net Exposure Budgets

| Regime | Target Gross Exposure | Net Exposure Range |
|:---|:---|:---|:---|:---|
| Low Risk (trending, wide breadth, neutral sentiment) | 80% | ±20% |
| Medium Risk (normal vol, normal liquidity, moderate correlation) | 50% | ±15% |
| High Risk (high vol, tight liquidity, narrow breadth, extreme sentiment) | 20% | ±10% |

- Target Gross Exposure: normal operating level
- Max Gross Exposure: hard ceiling (must not exceed 100%)
- Net Exposure Range: upper bound for long bias, lower bound for short bias

**IMPORTANT**: 

- The position ratio should be moderate. Both excessively high (>80%) and excessively low (<15%) are undesirable. The strategy needs to be adjusted accordingly.
- Bull market: Long position ratio should be greater than short position ratio
- Bear market: Short position ratio should be greater than long position ratio
- Do not rely on post-trade adjustments or forced liquidations to comply with these limits. Calculate the maximum allowable quantity before placing any order.

## 3. New Position Entry Rules

New buys/shorts allowed ONLY if ALL conditions met:

- Current Gross <= Target Gross
- Current Cash >= Min Cash (for longs) OR sufficient margin (for shorts)
- Position size respects per-name caps
- Regime != High Risk (or only small entries allowed)

If not allowed -> maintenance-only mode (trim only).

## 4. High Risk Regime Handling

When High Risk regime:

- No new long or short entries (override all factor signals)
- Daily trimming until Gross Exposure <= Max Gross Exposure
- If already within limits, maintain but do not add
- In bull markets, exercise caution when initiating short positions. In bear markets, exercise caution when initiating long positions. Maintain disciplined long/short position management

## 5. Strategy Validation

Before live deployment, validate using backtest:

- Sharpe Ratio >= 1.0
- Max Drawdown <= 10%
- Calmar Ratio >= 1.0

## 6. Note

Always check gross position rate and net gross position of your account. Always close positions first, then open new positions based on the account's remaining available capital.

**Reference**
```python
# strategy.py
@register_hook
def position_sizing_example():
    account = get_account_dict()
    watchlist = account.get("watch_list", [])
    current_positions = {p["symbol"]: p for p in account.get("positions", [])}
    available_cash = account.get("available_cash", 0)
    total_assets = account.get("total_assets", 0)
    gross_position_rate = account.get("gross_position_rate", 0)
    
    # Hard limits
    MAX_GROSS_RATE = 0.8
    LONG_CAP_RATE = 0.6   # Max long allocation as % of total assets
    SHORT_CAP_RATE = 0.2  # Max short allocation as % of total assets
    
    # Pre-allocate hard caps
    max_long_value = total_assets * LONG_CAP_RATE
    max_short_value = total_assets * SHORT_CAP_RATE
    
    # Generate signals (commented - replace with actual logic)
    # long_signals = [...]  # List of {"symbol": str, "score": float, "price": float}
    # short_signals = [...]
    
    long_signals = []
    short_signals = []

    # Close all existing positions first (full rebalance)
    for symbol, pos in current_positions.items():
        qty = pos.get("quantity", 0)
        current_price = pos.get("current_price", 0)
        
        if qty > 0:  # Close long position
            add_order(
                symbol=symbol,
                order_type="SELL",
                price=current_price,
                quantity=abs(qty)
            )
        elif qty < 0:  # Close short position
            add_order(
                symbol=symbol,
                order_type="BUY",
                price=current_price,
                quantity=abs(qty)
            )
    
    # Calculate current long/short values
    current_long_value = sum(
        p.get("market_value", 0) for p in current_positions.values() if p.get("quantity", 0) > 0
    )
    current_short_value = abs(sum(
        p.get("market_value", 0) for p in current_positions.values() if p.get("quantity", 0) < 0
    ))
    
    # Calculate remaining capacity
    remaining_long_capacity = max_long_value - current_long_value
    remaining_short_capacity = max_short_value - current_short_value
    
    # Close positions not in signals
    long_symbols_to_keep = {s["symbol"] for s in long_signals}
    short_symbols_to_keep = {s["symbol"] for s in short_signals}
    
    for symbol, pos in current_positions.items():
        qty = pos.get("quantity", 0)
        current_price = pos.get("current_price", 0)
        
        if qty > 0 and symbol not in long_symbols_to_keep:
            # SELL to close long
            add_order(
                symbol=symbol,
                order_type="SELL",
                price=current_price,
                quantity=abs(qty)
            )
        elif qty < 0 and symbol not in short_symbols_to_keep:
            # BUY to cover short
            add_order(
                symbol=symbol,
                order_type="BUY",
                price=current_price,
                quantity=abs(qty)
            )
    
    # Open new long positions
    if long_signals and remaining_long_capacity > 0:
        long_allocation = remaining_long_capacity / len(long_signals)
        
        for signal in long_signals:
            symbol = signal["symbol"]
            price = signal["price"]
            
            # Skip if already holding long
            if symbol in current_positions and current_positions[symbol].get("quantity", 0) > 0:
                continue
            
            target_value = min(long_allocation, remaining_long_capacity)
            shares_to_buy = int(target_value / price / 100) * 100
            
            if shares_to_buy > 0:
                cost = shares_to_buy * price
                
                if cost <= available_cash and cost <= remaining_long_capacity:
                    # BUY signal
                    add_order(
                        symbol=symbol,
                        order_type="BUY",
                        price=price,
                        quantity=shares_to_buy
                    )
                    available_cash -= cost
                    remaining_long_capacity -= cost
    
    # Open new short positions
    if short_signals and remaining_short_capacity > 0:
        short_allocation = remaining_short_capacity / len(short_signals)
        
        for signal in short_signals:
            symbol = signal["symbol"]
            price = signal["price"]
            
            # Skip if already holding short
            if symbol in current_positions and current_positions[symbol].get("quantity", 0) < 0:
                continue
            
            target_value = min(short_allocation, remaining_short_capacity)
            shares_to_short = int(target_value / price / 100) * 100
            
            if shares_to_short > 0:
                # SELL short signal
                add_order(
                    symbol=symbol,
                    order_type="SELL",
                    price=price,
                    quantity=shares_to_short
                )
                remaining_short_capacity -= shares_to_short * price
```