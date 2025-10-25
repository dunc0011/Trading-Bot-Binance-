"""
Triple Barrier Labeling Method
Advanced target labeling that considers both profit targets and stop losses
More realistic than simple forward returns
"""
import numpy as np
import pandas as pd
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class TripleBarrierLabeler:
    """
    Implements triple barrier method for labeling training data
    
    Three barriers:
    1. Upper barrier: Take profit level
    2. Lower barrier: Stop loss level
    3. Vertical barrier: Maximum holding period
    
    Label is determined by which barrier is hit first
    """
    
    def __init__(self,
                 profit_target: float = 0.02,  # 2% profit target
                 stop_loss: float = 0.01,      # 1% stop loss
                 max_holding_periods: int = 24  # Max holding periods
                ):
        """
        Args:
            profit_target: Profit target as decimal (0.02 = 2%)
            stop_loss: Stop loss as decimal (0.01 = 1%)
            max_holding_periods: Maximum number of periods to hold
        """
        self.profit_target = profit_target
        self.stop_loss = stop_loss
        self.max_holding_periods = max_holding_periods
    
    def _get_vertical_barrier(self, close: pd.Series, start_idx: int) -> int:
        """Get vertical barrier (time-based exit)"""
        end_idx = min(start_idx + self.max_holding_periods, len(close) - 1)
        return end_idx
    
    def _get_horizontal_barriers(self, 
                                 close: pd.Series, 
                                 start_idx: int,
                                 volatility_adj: bool = True) -> Tuple[float, float]:
        """
        Get horizontal barriers (price-based exits)
        
        Args:
            close: Close price series
            start_idx: Starting index
            volatility_adj: If True, adjust barriers based on ATR
            
        Returns:
            Tuple of (upper_barrier, lower_barrier) prices
        """
        entry_price = close.iloc[start_idx]
        
        # Volatility adjustment
        if volatility_adj and start_idx >= 14:
            # Calculate ATR
            recent_returns = close.pct_change().iloc[max(0, start_idx-14):start_idx]
            atr_pct = recent_returns.std() * np.sqrt(14)  # Annualized
            
            # Scale barriers by volatility (min 0.5x, max 2x)
            vol_multiplier = np.clip(atr_pct / 0.02, 0.5, 2.0)
        else:
            vol_multiplier = 1.0
        
        upper_barrier = entry_price * (1 + self.profit_target * vol_multiplier)
        lower_barrier = entry_price * (1 - self.stop_loss * vol_multiplier)
        
        return upper_barrier, lower_barrier
    
    def _get_first_touch(self,
                        close: pd.Series,
                        start_idx: int,
                        upper_barrier: float,
                        lower_barrier: float,
                        end_idx: int) -> Tuple[int, str]:
        """
        Find which barrier is touched first
        
        Returns:
            Tuple of (touch_idx, barrier_type)
            barrier_type: 'profit', 'loss', or 'time'
        """
        prices = close.iloc[start_idx:end_idx+1]
        
        for i, price in enumerate(prices):
            if i == 0:  # Skip entry point
                continue
            
            if price >= upper_barrier:
                return start_idx + i, 'profit'
            elif price <= lower_barrier:
                return start_idx + i, 'loss'
        
        # No price barrier touched, hit time barrier
        return end_idx, 'time'
    
    def label_data(self, 
                   df: pd.DataFrame,
                   volatility_adj: bool = True) -> pd.DataFrame:
        """
        Apply triple barrier labeling to price data
        
        Args:
            df: DataFrame with 'close' column
            volatility_adj: Whether to adjust barriers by volatility
            
        Returns:
            DataFrame with additional columns:
                - label: 1 (profitable), 0 (loss or timeout)
                - return: Actual return achieved
                - holding_period: Number of periods held
                - exit_reason: 'profit', 'loss', or 'time'
        """
        close = df['close']
        labels = []
        returns = []
        holding_periods = []
        exit_reasons = []
        
        logger.info(f"Labeling {len(df)} candles with triple barrier method")
        
        for i in range(len(close)):
            # Can't label last few candles (no future data)
            if i >= len(close) - self.max_holding_periods:
                labels.append(np.nan)
                returns.append(np.nan)
                holding_periods.append(np.nan)
                exit_reasons.append(None)
                continue
            
            # Get barriers
            end_idx = self._get_vertical_barrier(close, i)
            upper, lower = self._get_horizontal_barriers(close, i, volatility_adj)
            
            # Find first touch
            touch_idx, barrier_type = self._get_first_touch(close, i, upper, lower, end_idx)
            
            # Calculate return
            entry_price = close.iloc[i]
            exit_price = close.iloc[touch_idx]
            ret = (exit_price - entry_price) / entry_price
            
            # Label: 1 if profitable, 0 otherwise
            label = 1 if barrier_type == 'profit' else 0
            
            # Store results
            labels.append(label)
            returns.append(ret)
            holding_periods.append(touch_idx - i)
            exit_reasons.append(barrier_type)
        
        # Add to dataframe
        result = df.copy()
        result['label'] = labels
        result['return'] = returns
        result['holding_period'] = holding_periods
        result['exit_reason'] = exit_reasons
        
        # Drop NaN rows
        result = result.dropna(subset=['label'])
        
        # Log statistics
        if len(result) > 0:
            profit_pct = (result['label'] == 1).sum() / len(result) * 100
            loss_pct = (result['exit_reason'] == 'loss').sum() / len(result) * 100
            time_pct = (result['exit_reason'] == 'time').sum() / len(result) * 100
            avg_hold = result['holding_period'].mean()
            
            logger.info(f"Label distribution:")
            logger.info(f"  Profit: {profit_pct:.1f}%")
            logger.info(f"  Loss: {loss_pct:.1f}%")
            logger.info(f"  Time: {time_pct:.1f}%")
            logger.info(f"  Avg holding period: {avg_hold:.1f} candles")
        
        return result


class MetaLabeler:
    """
    Meta-labeling: Instead of predicting direction, predict if model's
    primary signal will be profitable
    
    This is a two-stage approach:
    1. Primary model generates signals
    2. Meta-model filters signals (improves precision)
    """
    
    def __init__(self, profit_threshold: float = 0.005):
        self.profit_threshold = profit_threshold
    
    def create_meta_labels(self,
                          df: pd.DataFrame,
                          primary_signals: pd.Series,
                          returns: pd.Series) -> pd.Series:
        """
        Create meta-labels: 1 if primary signal was profitable, 0 otherwise
        
        Args:
            df: Price dataframe
            primary_signals: Series of 1/-1/0 signals from primary model
            returns: Forward returns
            
        Returns:
            Series of meta-labels (1 = signal was profitable, 0 = not)
        """
        # For each primary signal, check if it would be profitable
        meta_labels = pd.Series(index=df.index, dtype=float)
        
        for idx in primary_signals.index:
            if primary_signals.loc[idx] == 1:  # Buy signal
                # Check if next return is above threshold
                if idx in returns.index:
                    meta_labels.loc[idx] = 1 if returns.loc[idx] > self.profit_threshold else 0
        
        return meta_labels.dropna()


def optimize_holding_period(df: pd.DataFrame, 
                            max_periods: int = 50,
                            step: int = 5) -> int:
    """
    Find optimal holding period by testing different horizons
    
    Returns:
        Optimal number of periods to hold
    """
    best_sharpe = -np.inf
    best_period = max_periods // 2
    
    close = df['close']
    
    for period in range(step, max_periods + 1, step):
        returns = close.pct_change(period)
        
        # Calculate Sharpe ratio
        mean_ret = returns.mean()
        std_ret = returns.std()
        
        if std_ret > 0:
            sharpe = mean_ret / std_ret * np.sqrt(252 / period)
            
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_period = period
    
    logger.info(f"Optimal holding period: {best_period} candles (Sharpe: {best_sharpe:.3f})")
    return best_period
