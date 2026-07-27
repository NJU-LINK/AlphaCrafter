import os
import json
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .schemas import AccountSchema, OrderSchema, OrderResultSchema, OrderStatus, OrderType, PositionData, PositionDirection


class Exchange:
    """
    Exchange simulator for backtesting trading strategies (US market)
    
    Handles order matching, account management, and data persistence
    Follows US market rules: T+0 settlement, supports short selling
    """
    
    def __init__(self, dataset_dir_path: str, account_file_path: str, date_file_path: str):
        """
        Initialize the exchange
        
        Args:
            dataset_dir_path: Path to the folder containing stock CSV files
            account_file_path: Path to the account file for persistence
            date_file_path: Path to the date.json file containing current_date and trading_days
            
        Raises:
            FileNotFoundError: If account file does not exist
        """
        self.dataset_dir_path = Path(dataset_dir_path)
        self.account_file_path = Path(account_file_path)
        self.date_file_path = Path(date_file_path)
        
        # Check if account file exists
        if not self.account_file_path.exists():
            raise FileNotFoundError(f"Account file not found: {account_file_path}")
        
        # Check if date file exists
        if not self.date_file_path.exists():
            raise FileNotFoundError(f"Date file not found: {date_file_path}")
        
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.account: AccountSchema = None
        
        # Commission rate (US market: typically lower)
        self.commission_rate = 0.0001
        
        # Margin requirements for short selling (percentage of position value)
        self.short_margin_requirement = 0.5
        
        # Maintenance margin requirement (minimum equity percentage)
        self.maintenance_margin = 0.3
        
        # Interest rate for short proceeds (not implemented in this simple version)
        self.short_interest_rate = 0.0

        # Load market data
        self._load_market_data()
    
    def _load_date_info(self) -> None:
        """Load date information from date.json"""
        with open(self.date_file_path, 'r') as f:
            date_data = json.load(f)
        
        self.current_date_str = date_data.get('current_date')
        self.trading_days = date_data.get('trading_days', [])
        
        if not self.current_date_str:
            raise ValueError("current_date not found in date.json")
        if not self.trading_days:
            raise ValueError("trading_days not found in date.json")
        
        self.current_date = datetime.strptime(self.current_date_str, "%Y-%m-%d")
        self.current_date = self.current_date.replace(hour=16, minute=0)  # US market closes at 4 PM
        
    def _get_previous_trading_day(self) -> Optional[str]:
        """Get the previous trading day from the trading_days list"""
        try:
            current_idx = self.trading_days.index(self.current_date_str)
            if current_idx > 0:
                return self.trading_days[current_idx - 1]
            return None
        except ValueError:
            return None
        
    def _load_market_data(self) -> None:
        """Load all CSV files from the dataset folder"""
        if not self.dataset_dir_path.exists():
            raise FileNotFoundError(f"Dataset path not found: {self.dataset_dir_path}")
        
        csv_files = self.dataset_dir_path.glob("*.csv")
        for csv_file in csv_files:
            try:
                # Extract stock code from filename (remove .csv)
                stock_code = csv_file.stem
                
                # Load CSV with proper date parsing
                df = pd.read_csv(csv_file)
                df['date'] = pd.to_datetime(df['date'])
                df.sort_values('date', inplace=True)
                
                self.market_data[stock_code] = df
            except Exception as e:
                print(f"Error loading {csv_file}: {e}")
    
    def _load_account(self) -> AccountSchema:
        """Load account from JSON file"""
        try:
            with open(self.account_file_path, 'r') as f:
                data = json.load(f)
            
            # Convert positions from list
            positions = []
            for pos_data in data.get('positions', []):
                # Ensure direction field exists (default to LONG for backward compatibility)
                if 'direction' not in pos_data:
                    pos_data['direction'] = PositionDirection.LONG
                positions.append(PositionData(**pos_data))
            
            # Convert orders
            orders = []
            for order_data in data.get('orders', []):
                # Convert string timestamps back to datetime
                if 'timestamp' in order_data and isinstance(order_data['timestamp'], str):
                    order_data['timestamp'] = datetime.fromisoformat(order_data['timestamp'])
                orders.append(OrderSchema(**order_data))
            

            return AccountSchema(
                total_assets=data.get('total_assets', 0),
                net_assets=data.get('net_assets', 0),
                available_cash=data.get('available_cash', 0),
                market_value=data.get('market_value', 0),
                total_profit_loss=data.get('total_profit_loss', 0),
                total_profit_loss_rate=data.get('total_profit_loss_rate', 0),
                gross_position_rate=data.get('gross_position_rate', 0),
                net_position_rate=data.get('net_position_rate', 0),
                positions=positions,
                orders=orders,
                watch_list=data.get('watch_list', []),
            )

        except Exception as e:
            raise RuntimeError(f"Failed to load account from {self.account_file_path}: {e}")
    
    def _save_account(self) -> None:
        """Save account to JSON file with proper decimal formatting"""
        # Convert to dict for JSON serialization
        account_dict = self.account.model_dump()
        
        # Format decimal values
        for field in ['total_profit_loss_rate', 'gross_position_rate', 'net_position_rate']:
            if field in account_dict:
                account_dict[field] = round(account_dict[field], 4)
        
        for field in ['total_assets', 'net_assets', 'available_cash', 'market_value', 'total_profit_loss']:
            if field in account_dict:
                account_dict[field] = round(account_dict[field], 4)
        
        # Format positions
        for position in account_dict.get('positions', []):
            for field in ['cost_price', 'current_price', 'market_value', 'profit_loss', 'profit_loss_rate']:
                if field in position:
                    position[field] = round(position[field], 4)
            # Ensure direction is stored as string
            if 'direction' in position and hasattr(position['direction'], 'value'):
                position['direction'] = position['direction'].value
            # quantity should be negative for shorts
            if position.get('direction') == 'SHORT' and position.get('quantity', 0) > 0:
                position['quantity'] = -position['quantity']
            if position.get('direction') == 'SHORT' and position.get('available_quantity', 0) > 0:
                position['available_quantity'] = -position['available_quantity']
        
        # Format orders
        for order in account_dict.get('orders', []):
            if 'price' in order:
                order['price'] = round(order['price'], 4)
            
            # Convert datetime objects to strings
            if isinstance(order.get('timestamp'), datetime):
                order['timestamp'] = order['timestamp'].isoformat()
        
        # Ensure directory exists
        self.account_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.account_file_path, 'w') as f:
            json.dump(account_dict, f, indent=2, default=str)
    
    def _get_price_data(self, symbol: str, date: datetime) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Get price data for a symbol on a given date.
        If exact date not found, use the most recent historical data.
        
        Returns:
            Tuple of (low_price, high_price, close_price)
            Returns (None, None, None) if no data found (suspended stock)
        """
        if symbol not in self.market_data:
            return None, None, None
        
        df = self.market_data[symbol]
        date_str = date.strftime('%Y-%m-%d')
        
        # Check if exact date exists
        exact_match = df[df['date'] == date_str]
        if not exact_match.empty:
            row = exact_match.iloc[0]
            return row['low'], row['high'], row['close']
        
        # If exact date not found, find the most recent date before the target date
        past_data = df[df['date'] < date_str]
        if not past_data.empty:
            latest_row = past_data.iloc[-1]
            print(f"Warning: No data for {symbol} on {date_str}, using data from {latest_row['date']}")
            return latest_row['low'], latest_row['high'], latest_row['close']
        
        # No data found - stock is suspended
        print(f"Warning: No data found for {symbol} on {date_str} - stock may be suspended")
        return None, None, None
    
    def _find_position(self, symbol: str, direction: PositionDirection) -> Optional[PositionData]:
        """Find position by symbol and direction in positions list"""
        for position in self.account.positions:
            if position.symbol == symbol and position.direction == direction:
                return position
        return None
    
    def _remove_position(self, symbol: str, direction: PositionDirection) -> None:
        """Remove position by symbol and direction from positions list"""
        self.account.positions = [
            p for p in self.account.positions 
            if not (p.symbol == symbol and p.direction == direction)
        ]
    
    def _calculate_margin_requirement(self) -> float:
        """
        Calculate total margin requirement for all positions
        Long positions: 0 margin (if using cash)
        Short positions: require margin = abs(market_value) * short_margin_requirement
        """
        total_margin = 0.0
        for position in self.account.positions:
            if position.direction == PositionDirection.SHORT:
                total_margin += abs(position.market_value) * self.short_margin_requirement
        return total_margin
    
    def _calculate_equity(self) -> float:
        """
        Calculate account equity (net assets)
        Equity = Cash + Total Market Value (including negative values for shorts)
        """
        total_market_value = sum(p.market_value for p in self.account.positions)
        return self.account.available_cash + total_market_value
    
    def _check_margin_call(self) -> List[OrderResultSchema]:
        """
        Check if margin call is triggered and force liquidate positions if needed
        
        Returns:
            List of liquidation order results
        """
        liquidation_results = []
        
        # Calculate current equity and margin requirement
        equity = self._calculate_equity()
        margin_requirement = self._calculate_margin_requirement()
        
        # Check if equity is below maintenance margin
        # Maintenance margin requirement: equity >= margin_requirement * maintenance_margin_ratio
        required_equity = margin_requirement * self.maintenance_margin
        
        if equity < required_equity and margin_requirement > 0:
            print(f"Margin call triggered! Equity: {equity:.2f}, Required: {required_equity:.2f}")
            
            # Need to reduce positions to meet margin requirements
            # Sort positions: close shorts first (most risky), then longs
            positions_to_liquidate = []
            
            # Collect short positions (negative market value)
            short_positions = [p for p in self.account.positions if p.direction == PositionDirection.SHORT]
            long_positions = [p for p in self.account.positions if p.direction == PositionDirection.LONG]
            
            # Sort short positions by loss (largest loss first)
            short_positions.sort(key=lambda p: p.profit_loss)
            positions_to_liquidate.extend(short_positions)
            positions_to_liquidate.extend(long_positions)
            
            # Force liquidate until margin requirement is met
            for position in positions_to_liquidate:
                if equity >= required_equity:
                    break
                
                # Get current price (use last available price)
                _, _, current_price = self._get_price_data(position.symbol, self.current_date)
                
                if current_price is None:
                    # Can't liquidate if no price data
                    continue
                
                # Liquidate entire position (using absolute quantity)
                abs_quantity = abs(position.quantity)
                executed_amount = current_price * abs_quantity
                commission = round(executed_amount * self.commission_rate, 4)
                
                if position.direction == PositionDirection.LONG:
                    # Close long position
                    self.account.available_cash += (executed_amount - commission)
                    position.quantity = 0
                    liquidation_results.append(OrderResultSchema(
                        order_id=f"MARGIN_LIQUIDATION_{position.symbol}",
                        symbol=position.symbol,
                        order_type=OrderType.SELL,
                        status=OrderStatus.SUCCESS,
                        timestamp=self.current_date,
                        executed_quantity=abs_quantity,
                        executed_price=current_price,
                        executed_amount=executed_amount,
                        commission=commission,
                        message="Margin call: forced liquidation"
                    ))
                else:  # SHORT
                    # Cover short position (buy to close)
                    self.account.available_cash -= (executed_amount + commission)
                    position.quantity = 0
                    liquidation_results.append(OrderResultSchema(
                        order_id=f"MARGIN_LIQUIDATION_{position.symbol}",
                        symbol=position.symbol,
                        order_type=OrderType.BUY,
                        status=OrderStatus.SUCCESS,
                        timestamp=self.current_date,
                        executed_quantity=abs_quantity,
                        executed_price=current_price,
                        executed_amount=executed_amount,
                        commission=commission,
                        message="Margin call: forced liquidation"
                    ))
                
                # Remove position
                self._remove_position(position.symbol, position.direction)
                
                # Recalculate equity
                equity = self._calculate_equity()
            
            # If still below requirements, account is bankrupt
            if equity < 0:
                print(f"Account bankrupt! Equity: {equity:.2f}")
                liquidation_results.append(OrderResultSchema(
                    order_id="BANKRUPTCY",
                    symbol="",
                    order_type=None,
                    status=OrderStatus.FAILED,
                    timestamp=self.current_date,
                    executed_quantity=0,
                    executed_price=None,
                    executed_amount=0,
                    commission=0,
                    message="Account bankrupt due to margin call"
                ))
        
        return liquidation_results
    
    def _update_order_statuses(self) -> None:
        """
        Update order statuses based on age (US market rules)
        - PENDING > 7 trading days → EXPIRED
        - Any order > 14 trading days → removed
        """
        updated_orders = []
        
        for order in self.account.orders:
            try:
                order_idx = self.trading_days.index(order.timestamp.strftime('%Y-%m-%d'))
                current_idx = self.trading_days.index(self.current_date_str)
                days_diff = current_idx - order_idx
            except ValueError:
                days_diff = (self.current_date - order.timestamp).days
            
            if days_diff > 14:
                # Orders older than 14 trading days are removed
                continue
            
            if order.status == OrderStatus.PENDING and days_diff > 7:
                # PENDING older than 7 trading days becomes EXPIRED
                order.status = OrderStatus.EXPIRED
                updated_orders.append(order)
            else:
                updated_orders.append(order)
        
        self.account.orders = updated_orders
    
    def _update_account_metrics(self) -> None:
        """Update account metrics based on current positions and prices"""
        total_market_value = 0
        total_long_market_value = 0
        total_short_market_value = 0
        
        # Update each position with current price
        for position in self.account.positions:
            # Get current price
            _, _, current_price = self._get_price_data(position.symbol, self.current_date)
            
            if current_price is not None:
                # Update position with current price
                position.current_price = current_price
                # market_value = quantity * current_price (quantity can be negative for shorts)
                position.market_value = position.quantity * current_price
                
                # Calculate profit/loss based on direction
                if position.direction == PositionDirection.LONG:
                    position.profit_loss = (current_price - position.cost_price) * position.quantity
                else:  # SHORT
                    # For shorts: profit = (cost_price - current_price) * abs(quantity)
                    position.profit_loss = (position.cost_price - current_price) * abs(position.quantity)
                
                # Calculate profit/loss rate
                if position.cost_price > 0 and position.quantity != 0:
                    cost_value = abs(position.cost_price * position.quantity)
                    position.profit_loss_rate = round(position.profit_loss / cost_value, 4)
                else:
                    position.profit_loss_rate = 0
                
                total_market_value += position.market_value
                if position.direction == PositionDirection.LONG:
                    total_long_market_value += position.market_value
                else:
                    total_short_market_value += position.market_value
            else:
                # Stock suspended - keep position but don't update
                total_market_value += position.market_value
                if position.direction == PositionDirection.LONG:
                    total_long_market_value += position.market_value
                else:
                    total_short_market_value += position.market_value
        
        # Update account metrics
        self.account.market_value = round(total_market_value, 4)
        
        # Net assets (equity) = cash + total market value
        self.account.net_assets = round(self.account.available_cash + total_market_value, 4)
        self.account.total_assets = self.account.net_assets
        
        # Calculate total profit/loss based on total assets vs initial capital
        initial_capital = 10000000  # Initial capital is 10 million USD
        
        # total_profit_loss = total_assets - initial_capital
        self.account.total_profit_loss = round(self.account.total_assets - initial_capital, 4)
        
        # total_profit_loss_rate = (total_assets - initial_capital) / initial_capital
        if initial_capital > 0:
            total_return = (self.account.total_assets - initial_capital) / initial_capital
            self.account.total_profit_loss_rate = round(total_return, 4)
        else:
            self.account.total_profit_loss_rate = 0
        
        # Gross position rate (absolute exposure / net assets)
        gross_exposure = sum(abs(p.market_value) for p in self.account.positions)
        self.account.gross_position_rate = round(gross_exposure / self.account.net_assets, 4) if self.account.net_assets != 0 else 0
        
        # Net position rate (long - short) / net assets
        net_exposure = total_long_market_value + total_short_market_value
        self.account.net_position_rate = round(net_exposure / self.account.net_assets, 4) if self.account.net_assets != 0 else 0
    
    def _process_orders(self) -> List[OrderResultSchema]:
        """
        Process all pending orders and execute those that can be matched
        
        Returns:
            List of order results for orders that were processed (SUCCESS or FAILED)
        """
        results = []
        execution_time = self.current_date
        
        orders_to_process = list(self.account.orders)
        
        for order in orders_to_process:
            if order.status != OrderStatus.PENDING:
                continue
            
            # Get price data for the day
            low, high, close = self._get_price_data(order.symbol, self.current_date)
            
            if low is None or high is None:
                # No market data - order cannot be executed
                # Keep as PENDING for future days
                print(f"Order {order.order_id}: Cannot execute - no market data for {order.symbol}")
                continue
            
            # Check if order price is within the day's range
            if low <= order.price <= high:
                executed_price = close
                executed_amount = executed_price * order.quantity
                commission = round(executed_amount * self.commission_rate, 4)
                executed_amount = round(executed_amount, 4)
                
                # Process based on order type
                if order.order_type == OrderType.BUY:
                    # BUY can be either opening LONG or closing SHORT
                    
                    # First check if there's a SHORT position to close
                    short_position = self._find_position(order.symbol, PositionDirection.SHORT)
                    
                    if short_position and short_position.quantity < 0:
                        # This is a buy to cover short position
                        abs_short_quantity = abs(short_position.quantity)
                        cover_quantity = min(order.quantity, abs_short_quantity)
                        
                        # Calculate profit/loss on covered shares
                        cover_profit = (short_position.cost_price - executed_price) * cover_quantity
                        
                        # Update cash (subtract buy cost and commission)
                        cash_change = -(executed_price * cover_quantity + commission)
                        self.account.available_cash = round(self.account.available_cash + cash_change, 4)
                        
                        # Update position (reduce absolute quantity)
                        short_position.quantity += cover_quantity  # Adding positive reduces negative
                        short_position.profit_loss += cover_profit
                        
                        if short_position.quantity >= 0:
                            self._remove_position(order.symbol, PositionDirection.SHORT)
                        
                        # If this covered all shares, mark order as success
                        if cover_quantity == order.quantity:
                            order.status = OrderStatus.SUCCESS
                            results.append(OrderResultSchema(
                                order_id=order.order_id,
                                symbol=order.symbol,
                                order_type=order.order_type,
                                status=OrderStatus.SUCCESS,
                                timestamp=execution_time,
                                executed_quantity=cover_quantity,
                                executed_price=executed_price,
                                executed_amount=executed_price * cover_quantity,
                                commission=commission,
                                message="Covered short position"
                            ))
                            continue
                        else:
                            # Partially covered, remaining quantity will be handled as new long
                            remaining_quantity = order.quantity - cover_quantity
                            
                            # Create a result for the covered portion
                            results.append(OrderResultSchema(
                                order_id=f"{order.order_id}",
                                symbol=order.symbol,
                                order_type=order.order_type,
                                status=OrderStatus.SUCCESS,
                                timestamp=execution_time,
                                executed_quantity=cover_quantity,
                                executed_price=executed_price,
                                executed_amount=executed_price * cover_quantity,
                                commission=round(executed_price * cover_quantity * self.commission_rate, 4),
                                message="Partially covered short position"
                            ))
                            
                            # Continue with remaining quantity as new long
                            order.quantity = remaining_quantity
                            executed_amount = executed_price * remaining_quantity
                            commission = round(executed_amount * self.commission_rate, 4)
                    
                    # Handle new long position (positive quantity)
                    total_cost = executed_amount + commission
                    
                    if self.account.available_cash >= total_cost:
                        self.account.available_cash = round(self.account.available_cash - total_cost, 4)
                        
                        # Find or create LONG position
                        long_position = self._find_position(order.symbol, PositionDirection.LONG)
                        
                        if long_position:
                            # Update existing position
                            total_quantity = long_position.quantity + order.quantity
                            total_cost_value = (long_position.quantity * long_position.cost_price) + (order.quantity * executed_price)
                            long_position.cost_price = round(total_cost_value / total_quantity, 4)
                            long_position.quantity = total_quantity
                        else:
                            # Create new long position (positive quantity)
                            new_position = PositionData(
                                symbol=order.symbol,
                                direction=PositionDirection.LONG,
                                quantity=order.quantity,
                                available_quantity=order.quantity,  # T+0: immediately available
                                cost_price=executed_price,
                                current_price=executed_price,
                                market_value=executed_amount,
                                profit_loss=0,
                                profit_loss_rate=0
                            )
                            self.account.positions.append(new_position)
                        
                        order.status = OrderStatus.SUCCESS
                        
                        results.append(OrderResultSchema(
                            order_id=order.order_id,
                            symbol=order.symbol,
                            order_type=order.order_type,
                            status=OrderStatus.SUCCESS,
                            timestamp=execution_time,
                            executed_quantity=order.quantity,
                            executed_price=executed_price,
                            executed_amount=executed_amount,
                            commission=commission
                        ))
                    else:
                        order.status = OrderStatus.FAILED
                        results.append(OrderResultSchema(
                            order_id=order.order_id,
                            symbol=order.symbol,
                            order_type=order.order_type,
                            status=OrderStatus.FAILED,
                            timestamp=execution_time,
                            executed_quantity=0,
                            executed_price=None,
                            executed_amount=0,
                            commission=0,
                            message="Insufficient funds"
                        ))
                    
                elif order.order_type == OrderType.SELL:
                    # SELL can be either closing LONG or opening SHORT
                    
                    # First check if there's a LONG position to close
                    long_position = self._find_position(order.symbol, PositionDirection.LONG)
                    
                    if long_position and long_position.quantity > 0:
                        # This is a sell to close long position
                        sell_quantity = min(order.quantity, long_position.quantity)
                        
                        # Calculate profit/loss
                        sell_profit = (executed_price - long_position.cost_price) * sell_quantity
                        
                        # Update cash (add proceeds minus commission)
                        self.account.available_cash = round(
                            self.account.available_cash + (executed_price * sell_quantity - commission), 4
                        )
                        
                        # Update position
                        long_position.quantity -= sell_quantity
                        long_position.profit_loss += sell_profit
                        
                        if long_position.quantity <= 0:
                            self._remove_position(order.symbol, PositionDirection.LONG)
                        
                        # If this sold all shares, mark order as success
                        if sell_quantity == order.quantity:
                            order.status = OrderStatus.SUCCESS
                            results.append(OrderResultSchema(
                                order_id=order.order_id,
                                symbol=order.symbol,
                                order_type=order.order_type,
                                status=OrderStatus.SUCCESS,
                                timestamp=execution_time,
                                executed_quantity=sell_quantity,
                                executed_price=executed_price,
                                executed_amount=executed_price * sell_quantity,
                                commission=commission,
                                message="Closed long position"
                            ))
                            continue
                        else:
                            # Partially sold, remaining quantity will be handled as new short
                            remaining_quantity = order.quantity - sell_quantity
                            
                            # Create a result for the sold portion
                            results.append(OrderResultSchema(
                                order_id=f"{order.order_id}",
                                symbol=order.symbol,
                                order_type=order.order_type,
                                status=OrderStatus.SUCCESS,
                                timestamp=execution_time,
                                executed_quantity=sell_quantity,
                                executed_price=executed_price,
                                executed_amount=executed_price * sell_quantity,
                                commission=round(executed_price * sell_quantity * self.commission_rate, 4),
                                message="Partially closed long position"
                            ))
                            
                            # Continue with remaining quantity as new short
                            order.quantity = remaining_quantity
                            executed_amount = executed_price * remaining_quantity
                            commission = round(executed_amount * self.commission_rate, 4)
                    
                    # Handle new short position (negative quantity)
                    # For short sales, cash increases (proceeds from sale)
                    self.account.available_cash = round(
                        self.account.available_cash + (executed_amount - commission), 4
                    )
                    
                    # Find or create SHORT position
                    short_position = self._find_position(order.symbol, PositionDirection.SHORT)
                    
                    if short_position:
                        # Update existing short position (quantity is negative)
                        total_quantity = short_position.quantity - order.quantity  # Subtract because order.quantity is positive
                        total_cost_value = (abs(short_position.quantity) * short_position.cost_price) + (order.quantity * executed_price)
                        short_position.cost_price = round(total_cost_value / abs(total_quantity), 4)
                        short_position.quantity = -abs(total_quantity)  # Keep negative
                    else:
                        # Create new short position (negative quantity)
                        new_position = PositionData(
                            symbol=order.symbol,
                            direction=PositionDirection.SHORT,
                            quantity=-order.quantity,  # Negative for shorts
                            available_quantity=-order.quantity,
                            cost_price=executed_price,
                            current_price=executed_price,
                            market_value=-executed_amount,  # Negative for shorts
                            profit_loss=0,
                            profit_loss_rate=0
                        )
                        self.account.positions.append(new_position)
                    
                    order.status = OrderStatus.SUCCESS
                    
                    results.append(OrderResultSchema(
                        order_id=order.order_id,
                        symbol=order.symbol,
                        order_type=order.order_type,
                        status=OrderStatus.SUCCESS,
                        timestamp=execution_time,
                        executed_quantity=order.quantity,
                        executed_price=executed_price,
                        executed_amount=executed_amount,
                        commission=commission,
                        message="Opened short position"
                    ))
            else:
                # Price out of range - order remains PENDING
                continue
        
        return results
    
    def pre_tick(self) -> None:
        """
        Execute pre-tick operations (order expiry, etc.)
        Called before strategy generates new orders.
        """
        self._load_date_info()
        self.account = self._load_account()
        self._update_order_statuses()
        self._save_account()


    def post_tick(self) -> List[OrderResultSchema]:
        """
        Execute post-tick operations (order matching, margin calls).
        Called after strategy generates orders.
        
        Returns:
            List of order results (SUCCESS or FAILED)
        """
        self._load_date_info()
        self.account = self._load_account()
        
        # Process pending orders
        execution_results = self._process_orders()
        
        # Update account metrics
        self._update_account_metrics()
        
        # Check margin calls
        margin_results = self._check_margin_call()
        if margin_results:
            self._update_account_metrics()
        
        # Save and return
        self._save_account()
        
        return execution_results + margin_results