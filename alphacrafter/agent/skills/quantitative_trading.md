---
name: quantitative_trading
description: Basic exchange trading APIs for order management and market data retrieval for quantitative trading.
---

# Quantitative Trading Skill Documentation

This skill provides basic exchange trading APIs that can be imported and used in any Python script for order management and market data access.

## Import
```python
from alphacrafter.sim.utils import (
    add_order,
    cancel_order,
    get_stock_daily_data,
    get_index_daily_data,
    get_account_dict,
)
```

## Usage

### `add_order`

Submit a new buy or sell order.

**Parameters**
- `symbol`: `str` - stock code
- `order_type`: `str` - "BUY" or "SELL"
- `price`: `float` - order price per share
- `quantity`: `int` - number of shares, must be multiple of 100

**Returns**
- `None`

**Example**
```python
add_order(
    symbol="AAPL",
    quantity=1000,
    order_type="BUY",
    price=38.0
)
```

### `cancel_order`

Cancel a pending order by its ID.

**Parameters**
- `order_id`: `str` - ID of the order to cancel, e.g., "ORD_A16B5DAB"

**Returns**
- `None`

**Example**
```python
cancel_order(order_id="ORD_A16B5DAB")
```

### `get_stock_daily_data`

Retrieve historical stock daily data (The returned DataFrame is sorted from old dates to recent, with the most recent trading day last).

**Parameters**
- `symbol`: `str` - stock code
- `days`: `int` - number of past trading days to retrieve, minimum 1 (including current date)

**Returns**
- `pd.DataFrame` - columns: date (<class 'pandas.Timestamp'>), open, close, high, low, volume, change, pct_change
- `None` - if no data available before or on current_date

**Example**
```python
df = get_stock_daily_data(symbol="AAPL", days=100)
```

### `get_index_daily_data`

Retrieve historical index daily data (The returned DataFrame is sorted from old dates to recent, with the most recent trading day last).

**Parameters**
- `symbol`: `str` - index code
- `days`: `int` - number of past trading days to retrieve, minimum 1 (including current date)

**Returns**
- `pd.DataFrame` - columns: date (<class 'pandas.Timestamp'>), open, close, high, low, volume, change, pct_change
- `None` - if no data available before or on current_date

**Example**
```python
df = get_index_daily_data(symbol="SPX", days=100)
```

### `get_account_dict`

Get access to the account state.

**Example**
```json
{
  "total_assets": 10000000.0,
  "net_assets": 10000000.0,
  "available_cash": 11250000.0,
  "market_value": -825000.0,
  "total_profit_loss": 0.0,
  "total_profit_loss_rate": 0.0,
  "gross_position_rate": 0.1575,
  "net_position_rate": -0.0825,
  "positions": [
    {
      "symbol": "NVDA",
      "direction": "LONG",
      "quantity": 10000,
      "cost_price": 38.0,
      "current_price": 38.0,
      "market_value": 380000.0,
      "profit_loss": 0.0,
      "profit_loss_rate": 0.0
    },
    {
      "symbol": "TSLA",
      "direction": "SHORT",
      "quantity": -5000,
      "cost_price": 250.0,
      "current_price": 250.0,
      "market_value": -1250000.0,
      "profit_loss": 0.0,
      "profit_loss_rate": 0.0
    }
  ],
  "orders": [],
  "watch_list": []
}
```

## Note

1. Retrieve Market Data
  - Use `get_account_dict()` to obtain `watch_list`
  - Iterate over watchlist symbols to fetch historical data via `get_stock_daily_data()`
  - Ensure sufficient historical window for factor calculation and validation
  - Example: `universe = {symbol: df for symbol in watchlist}` where each df contains historical prices and fundamentals
  - Some stocks may have limited historical data due to recent IPOs or late listing dates. Remeber to check `len(df) >= min_required_days`

2. Name Python scripts in `/scripts` as: `scripts/<agent_id>_<YYYYMMDD>_<description>.py` where `YYYYMMDD` refers to the current backtest simulation date (not the actual system date)

3. Shell Tool Output Handling
  - The shell tool returns terminal output directly to the agent
  - Use `print()` statements in your scripts to output key information (e.g., factor values, IC results, validation metrics)
  - For long outputs, consider truncation or summarization to stay within context limits
