from typing import Dict, Any, Callable, List, Optional, Tuple
import json
import os
import sys
import shutil
from time import sleep
from pathlib import Path
from datetime import datetime
import numpy as np

from .base import BaseTool
from alphacrafter.sim.hook import Hook


class BacktestTool(BaseTool):
    def __init__(self, date_file_path: str = "../persistent/date.json", 
                 account_file_path: str = "../persistent/account.json",
                 dataset_dir_path: str = "../persistent/stock_data", 
                 strategy_file_path: str = "./strategy.py",
                 log_file_path: str = "../logs/backtest_results.json",
                 mode: str = "a"):
        
        self.date_file_path = date_file_path
        self.account_file_path = account_file_path
        self.dataset_dir_path = dataset_dir_path
        self.strategy_file_path = strategy_file_path
        self.log_file_path = log_file_path
        self.mode = mode.lower()
        
        # Import appropriate Exchange based on mode
        if self.mode == "a":
            from alphacrafter.sim.exchange_a import Exchange
        elif self.mode == "us":
            from alphacrafter.sim.exchange_us import Exchange
        else:
            raise ValueError(f"Unsupported mode: {mode}. Supported modes: 'a' (A-share), 'us' (US stock)")
        
        # Store original file contents for restoration
        self.original_date_data = None
        self.original_account_data = None
        self.exchange = Exchange(dataset_dir_path, account_file_path, date_file_path)
        self.hook = Hook(strategy_file_path)
        # Backtest snapshots for this run
        self.backtest_snapshots = []

    def get_name(self) -> str:
        return "backtest"
    
    def _read_date_file(self, file_path: str) -> Dict[str, any]:
        """Read and parse a date.json file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Date file not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate required fields
        if 'current_date' not in data:
            raise ValueError(f"date.json missing 'current_date' field")
        if 'trading_days' not in data:
            raise ValueError(f"date.json missing 'trading_days' field")
        
        return data
    
    def _write_date_file(self, data: Dict[str, any], file_path: str) -> None:
        """Write updated data to date.json."""
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _read_account_file(self, file_path: str) -> Dict[str, any]:
        """Read account file and return parsed JSON."""
        if not os.path.exists(file_path):
            # Return default account structure if file doesn't exist
            return {
                "total_assets": 10000000.0,
                "net_assets": 10000000.0,
                "available_cash": 10000000.0,
                "market_value": 0.0,
                "total_profit_loss": 0.0,
                "total_profit_loss_rate": 0.0,
                "gross_position_rate": 0.0,
                "net_position_rate": 0.0,
                "positions": [],
                "orders": [],
                "watch_list": []
            }
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _write_account_file(self, data: Dict[str, any], file_path: str) -> None:
        """Write account data to file."""
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _save_original_state(self) -> None:
        """Save original state of date and account files."""
        # Save original date file
        if os.path.exists(self.date_file_path):
            self.original_date_data = self._read_date_file(self.date_file_path)
        else:
            self.original_date_data = None
        
        # Save original account file
        if os.path.exists(self.account_file_path):
            self.original_account_data = self._read_account_file(self.account_file_path)
        else:
            self.original_account_data = None
    
    def _restore_original_state(self) -> None:
        """Restore original state of date and account files."""
        # Restore date file
        if self.original_date_data is not None:
            self._write_date_file(self.original_date_data, self.date_file_path)
        elif os.path.exists(self.date_file_path):
            # If original didn't exist but file was created, remove it
            os.remove(self.date_file_path)
        
        # Restore account file
        if self.original_account_data is not None:
            self._write_account_file(self.original_account_data, self.account_file_path)
        elif os.path.exists(self.account_file_path):
            # If original didn't exist but file was created, remove it
            os.remove(self.account_file_path)
    
    def _log_account_snapshot(self, date: str, account_data: Dict[str, any]) -> None:
        """
        Log account snapshot to backtest snapshots list for metrics calculation.
        """
        try:
            # Create snapshot with only relevant metrics
            snapshot = {
                "date": date,
                "net_assets": account_data.get("net_assets", 0.0),
                "total_assets": account_data.get("total_assets", 0.0),
                "available_cash": account_data.get("available_cash", 0.0),
                "market_value": account_data.get("market_value", 0.0),
                "gross_position_rate": account_data.get("gross_position_rate", 0.0),
                "net_position_rate": account_data.get("net_position_rate", 0.0)
            }
            
            # Append to snapshots list
            self.backtest_snapshots.append(snapshot)
                
        except Exception as e:
            print(f"Warning: Failed to log account snapshot: {e}")
    
    def _find_past_trading_day(self, current_date: str, trading_days: List[str], days_ago: int) -> str:
        """
        Find the trading day N days ago.
        
        Args:
            current_date: Current date string (YYYY-MM-DD)
            trading_days: List of all trading days
            days_ago: Number of days to go back (positive) or forward (negative)
            
        Returns:
            Past trading date string (or first/last trading day if days_ago exceeds bounds)
        """
        try:
            # Find index of current date
            current_idx = trading_days.index(current_date)
            
            # Calculate target index
            target_idx = current_idx - days_ago
            
            # If beyond bounds, clamp to bounds
            if target_idx < 0:
                return trading_days[0]
            elif target_idx >= len(trading_days):
                return trading_days[-1]
            
            return trading_days[target_idx]
            
        except ValueError as e:
            if "not in list" in str(e):
                raise ValueError(f"Current date {current_date} not found in trading days list")
            raise e
    
    def _calculate_metrics(self) -> Dict[str, float]:
        """
        Calculate performance metrics from backtest snapshots based on net_assets.
        
        Returns:
            Dictionary with metrics: 
            - Total Return (%)
            - Annualized Return (%)
            - Sharpe Ratio
            - Max Drawdown (%)
            - Calmar Ratio
            - Average Gross Position Rate (%)
            - Average Net Position Rate (%)
        """
        if len(self.backtest_snapshots) < 2:
            return {
                "Total Return (%)": 0.0,
                "Annualized Return (%)": 0.0,
                "Sharpe Ratio": 0.0,
                "Max Drawdown (%)": 0.0,
                "Calmar Ratio": 0.0,
                "Average Gross Position Rate (%)": 0.0,
                "Average Net Position Rate (%)": 0.0
            }
        
        # Extract dates and net assets (using net_assets for return calculations)
        net_assets = [s["net_assets"] for s in self.backtest_snapshots]
        
        # Extract position rates if available
        gross_position_rates = [s.get("gross_position_rate", 0.0) for s in self.backtest_snapshots]
        net_position_rates = [s.get("net_position_rate", 0.0) for s in self.backtest_snapshots]
        
        # Calculate daily returns based on net_assets
        daily_returns = []
        for i in range(1, len(net_assets)):
            # Avoid division by zero
            if net_assets[i-1] > 0:
                daily_return = (net_assets[i] - net_assets[i-1]) / net_assets[i-1]
            else:
                daily_return = 0.0
            daily_returns.append(daily_return)
        
        if not daily_returns:
            return {
                "Total Return (%)": 0.0,
                "Annualized Return (%)": 0.0,
                "Sharpe Ratio": 0.0,
                "Max Drawdown (%)": 0.0,
                "Calmar Ratio": 0.0,
                "Average Gross Position Rate (%)": 0.0,
                "Average Net Position Rate (%)": 0.0
            }
        
        # Calculate metrics
        total_days = len(daily_returns)
        total_years = total_days / 252  # Assuming 252 trading days per year
        
        # 1. Total Return (based on net_assets)
        initial_net_assets = net_assets[0]
        final_net_assets = net_assets[-1]
        
        if initial_net_assets > 0:
            total_return = (final_net_assets - initial_net_assets) / initial_net_assets
        else:
            total_return = 0.0
        
        # 2. Annualized Return
        if total_years > 0 and initial_net_assets > 0:
            annualized_return = (1 + total_return) ** (1 / total_years) - 1
        else:
            annualized_return = 0.0
        
        # 3. Sharpe Ratio - using daily returns on net_assets
        # Assuming risk-free rate of 0.0016 (1.6%) annualized
        risk_free_rate = 0.0016
        daily_risk_free = risk_free_rate / 252
        
        # Calculate excess returns
        excess_returns = [r - daily_risk_free for r in daily_returns]
        
        avg_excess_return = np.mean(excess_returns) if excess_returns else 0.0
        std_excess_return = np.std(excess_returns) if len(excess_returns) > 1 else 1e-6
        
        # Annualize Sharpe Ratio
        if std_excess_return > 0:
            sharpe_ratio = (avg_excess_return / std_excess_return) * np.sqrt(252)
        else:
            sharpe_ratio = 0.0
        
        # 4. Max Drawdown (based on net_assets)
        peak = net_assets[0]
        max_drawdown = 0.0
        
        for value in net_assets:
            if value > peak:
                peak = value
            if peak > 0:
                drawdown = (peak - value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        
        # 5. Calmar Ratio
        calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else 0.0
        
        # 6. Average Position Rates
        avg_gross_position_rate = np.mean(gross_position_rates) if gross_position_rates else 0.0
        avg_net_position_rate = np.mean(net_position_rates) if net_position_rates else 0.0
        
        return {
            "Total Return (%)": round(total_return * 100, 2),
            "Annualized Return (%)": round(annualized_return * 100, 2),
            "Sharpe Ratio": round(sharpe_ratio, 2),
            "Max Drawdown (%)": round(max_drawdown * 100, 2),
            "Calmar Ratio": round(calmar_ratio, 2),
            "Average Gross Position Rate (%)": round(avg_gross_position_rate * 100, 2),
            "Average Net Position Rate (%)": round(avg_net_position_rate * 100, 2)
        }
    
    def _log_results(self, backtest_result: Dict[str, any]) -> None:
        """
        Log backtest results to the main log file as JSON list.
        """
        try:
            # Read existing logs or create new list
            if os.path.exists(self.log_file_path):
                with open(self.log_file_path, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            else:
                logs = []
            
            # Add timestamp to result
            backtest_result["timestamp"] = datetime.now().isoformat()
            
            # Append new result
            logs.append(backtest_result)
            
            # Write back to file
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Warning: Failed to log backtest results: {e}")
    
    def get_implementation(self) -> Callable:
        def backtest(days: int) -> str:
            """
            Run backtest from N days ago to today.
            
            Args:
                days: Number of trading days to go back
                
            Returns:
                String containing performance metrics
            """
            backtest_result = {
                "status": "success",
                "days": days,
                "error": None
            }
            
            # Reset snapshots for this run
            self.backtest_snapshots = []
            
            try:
                # Validate input
                if days <= 0:
                    error_msg = f"Error: days must be positive, got {days}"
                    backtest_result["status"] = "failed"
                    backtest_result["error"] = error_msg
                    self._log_results(backtest_result)
                    return error_msg
                
                if days >= 120:
                    days = 120  # Cap at 120 days to prevent excessively long backtests
                
                # Save original state
                self._save_original_state()
                
                # Read original date state
                date_data = self._read_date_file(self.date_file_path)
                current_date_str = date_data['current_date']
                trading_days = date_data['trading_days']
                
                # Calculate past date
                past_date_str = self._find_past_trading_day(
                    current_date_str, 
                    trading_days, 
                    days
                )
                
                # Set date to past date for backtest
                temp_date_data = {
                    "current_date": past_date_str,
                    "trading_days": trading_days
                }
                self._write_date_file(temp_date_data, self.date_file_path)
                
                print(f"Backtest period: {past_date_str} → {current_date_str} ({days} trading days)")
                
                # Log initial account snapshot
                initial_account = self._read_account_file(self.account_file_path)
                self._log_account_snapshot(past_date_str, initial_account)
                
                # Process each day sequentially
                next_date_str = past_date_str
                for i in range(days):
                    print(f"Processing day {i+1}/{days}...")
                    # Process exchange tick
                    self.exchange.pre_tick()
                    sleep(0.4)  # Small delay to simulate time passage   

                    # Execute strategy hook
                    self.hook.on_tick()
                    sleep(0.4)  # Small delay to simulate time passage

                    self.exchange.post_tick()
                    sleep(0.4)  # Small delay to simulate time passage        
                    
                    # Log account snapshot after exchange tick
                    current_account = self._read_account_file(self.account_file_path)
                    self._log_account_snapshot(next_date_str, current_account)

                    next_date_str = self._find_past_trading_day(
                        next_date_str, 
                        trading_days, 
                        -1  # Move forward one step
                    )
                    print(f"  Current trading day: {next_date_str}")
                    
                    temp_date_data['current_date'] = next_date_str

                    self._write_date_file(temp_date_data, self.date_file_path)
                    
                    print(f"  Day {i+1} completed")
                
                # Calculate metrics from snapshots
                metrics = self._calculate_metrics()
                
                # Prepare output
                output_lines = []
                output_lines.append(f"✅ Backtest completed: {past_date_str} → {current_date_str} ({days} trading days)")
                output_lines.append("")
                output_lines.append("📊 Performance Metrics (based on Net Assets):")
                for metric_name, metric_value in metrics.items():
                    output_lines.append(f"  {metric_name}: {metric_value}")
                
                # Prepare result for logging
                backtest_result["period"] = {
                    "start_date": past_date_str,
                    "end_date": current_date_str
                }
                backtest_result["metrics"] = metrics
                backtest_result["snapshots"] = self.backtest_snapshots  # Save snapshots for reference
                
                # Log successful result
                self._log_results(backtest_result)
                
                return "\n".join(output_lines)
                
            except Exception as e:
                import traceback
                error_msg = f"❌ Error during backtest execution: {str(e)}\n{traceback.format_exc()}"
                
                # Log failed result
                backtest_result["status"] = "failed"
                backtest_result["error"] = str(e)
                self._log_results(backtest_result)
                
                # Return error message immediately, no further execution
                return error_msg
            
            finally:
                # Always restore original state
                self._restore_original_state()
                
                # Clear snapshots
                self.backtest_snapshots = []
                
        return backtest
        
    
    def get_description(self, producer: str = "OpenAI") -> Dict[str, Any]:
        """
        Return tool description based on the producer.
        """
        if producer == "OpenAI":
            return {
                "type": "function",
                "name": self.get_name(),
                "description": (
                    "Run a backtest from N trading days ago to today using the strategy defined in `workspace/strategy.py`. Returns performance metrics including Total Return, Annualized Return, Sharpe Ratio, Max Drawdown, Calmar Ratio and Average Position Rates. Returns zero values when no orders are executed during the backtest period."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Number of trading days to go back for backtest (must be positive integer)",
                            "maximum": 252
                        }
                    },
                    "required": ["days"]
                }
            }
        else:
            raise ValueError(f"Unsupported producer: {producer}")