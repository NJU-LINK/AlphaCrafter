---
name: strategy_registration
description: Strategy hook decorator for automatic execution of trading logic
---

# Strategy Registration Skill Documentation

This skill provides a decorator to register a function that will be automatically executed by the step and backtest tool.

## Import
```python
from alphacrafter.sim.utils import register_hook
```
## Usage

Decorator to mark a function as the strategy hook.  The core strategy logic should be implemented in `strategy.py` using the `@register_hook` decorator. The function decorated with `@register_hook` will be automatically executed at each trading day. You can simply define your trading logic inside the function.

**Important Notes**:

- The decorated function is the exclusive entry point - no other functions will be called automatically
- The function must not accept any parameters - if parameters are defined, they will be ignored. The function must not return any value - any return value will be discarded
- All trading decisions must be made using the available trading APIs directly within the function body

**Parameters**
- `func`: `Callable` - the strategy function (No parameters and no return value)

**Implementation**
```python
def register_hook(func):
    func._is_hook = True
    return func
```

## Baseline Reference
Here is a reference strategy. You need to write scripts following this strategy's style.

```python
# strategy.py
@register_hook
def example_strategy():
    account = get_account_dict()
    watchlist = account.get("watch_list", [])
    current_positions = {p["symbol"]: p for p in account.get("positions", [])}
    total_assets = account.get("total_assets", 0)
    gross_position_rate = account.get("gross_position_rate", 0)
    
    LOOKBACK_DAYS = 20
    TOP_N = 50
    TARGET_GROSS_RATE = 0.6  # Target gross exposure
    
    # If gross exposure exceeds target, only trim, no new entries
    if gross_position_rate >= TARGET_GROSS_RATE:
        for symbol, pos in current_positions.items():
            qty = pos.get("quantity", 0)
            if qty > 0:
                add_order(
                    symbol=symbol,
                    order_type="SELL",
                    price=pos.get("current_price", 0),
                    quantity=abs(qty)
                )
        return
    
    # Calculate momentum scores
    stocks_with_momentum = []
    for symbol in watchlist:
        df = get_stock_daily_data(symbol=symbol, days=LOOKBACK_DAYS + 5)
        if df is None or len(df) < LOOKBACK_DAYS:
            continue
        
        df = df.sort_values("date")
        price_20d_ago = df.iloc[-LOOKBACK_DAYS]["close"]
        current_price = df.iloc[-1]["close"]
        momentum = (current_price - price_20d_ago) / price_20d_ago
        
        stocks_with_momentum.append({
            "symbol": symbol,
            "momentum": momentum,
            "current_price": current_price
        })
    
    stocks_with_momentum.sort(key=lambda x: x["momentum"], reverse=True)
    top_stocks = stocks_with_momentum[:TOP_N]
    symbols_to_keep = {s["symbol"] for s in top_stocks}
    
    # Close positions not in top N
    for symbol, pos in current_positions.items():
        if symbol not in symbols_to_keep:
            qty = pos.get("quantity", 0)
            if qty > 0:
                add_order(
                    symbol=symbol,
                    order_type="SELL",
                    price=pos.get("current_price", 0),
                    quantity=abs(qty)
                )
    
    # Calculate buying power: target position value - current long value
    target_position_value = total_assets * TARGET_GROSS_RATE
    current_long_value = sum(
        p.get("market_value", 0) for p in current_positions.values() 
        if p.get("quantity", 0) > 0 and p["symbol"] in symbols_to_keep
    )
    available_for_new = target_position_value - current_long_value
    
    if available_for_new <= 0:
        return
    
    # Allocate evenly among new positions
    value_per_stock = available_for_new / len(top_stocks)
    
    for stock in top_stocks:
        symbol = stock["symbol"]
        current_price = stock["current_price"]
        
        # Skip if already holding
        if symbol in current_positions and current_positions[symbol].get("quantity", 0) > 0:
            continue
        
        shares_to_buy = int(value_per_stock / current_price / 100) * 100
        
        if shares_to_buy > 0:
            add_order(
                symbol=symbol,
                order_type="BUY",
                price=current_price,
                quantity=shares_to_buy
            )
```