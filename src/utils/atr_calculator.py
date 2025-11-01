"""
ATR (Average True Range) Calculator
For dynamic trailing stops and volatility-based position sizing
"""
import pandas as pd
import numpy as np
from typing import List, Optional


def calculate_atr(klines: List, period: int = 14) -> Optional[float]:
    """
    Calculate ATR from klines data
    
    Args:
        klines: List of kline arrays [timestamp, open, high, low, close, volume, ...]
        period: ATR period (default 14)
        
    Returns:
        ATR value as percentage of price, or None if insufficient data
    """
    try:
        if len(klines) < period + 1:
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        # Convert to numeric
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['close'] = pd.to_numeric(df['close'])
        
        # Calculate True Range
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['prev_close'])
        df['tr3'] = abs(df['low'] - df['prev_close'])
        df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calculate ATR using EMA
        df['atr'] = df['true_range'].ewm(span=period, adjust=False).mean()
        
        # Return ATR as percentage of current price
        current_price = df['close'].iloc[-1]
        atr_value = df['atr'].iloc[-1]
        atr_pct = (atr_value / current_price) * 100
        
        return atr_pct
        
    except Exception as e:
        print(f"Error calculating ATR: {e}")
        return None


def calculate_atr_absolute(klines: List, period: int = 14) -> Optional[float]:
    """
    Calculate absolute ATR value (not percentage)
    
    Args:
        klines: List of kline arrays
        period: ATR period
        
    Returns:
        Absolute ATR value
    """
    try:
        if len(klines) < period + 1:
            return None
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['close'] = pd.to_numeric(df['close'])
        
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['prev_close'])
        df['tr3'] = abs(df['low'] - df['prev_close'])
        df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        df['atr'] = df['true_range'].ewm(span=period, adjust=False).mean()
        
        return df['atr'].iloc[-1]
        
    except Exception as e:
        print(f"Error calculating absolute ATR: {e}")
        return None


def get_volatility_regime(atr_pct: float) -> str:
    """
    Classify volatility regime based on ATR%
    
    Args:
        atr_pct: ATR as percentage
        
    Returns:
        'low', 'medium', or 'high'
    """
    if atr_pct < 0.5:
        return 'low'
    elif atr_pct < 1.5:
        return 'medium'
    else:
        return 'high'


def calculate_range_position(klines: List, lookback: int = 24) -> Optional[float]:
    """
    Calculate where current price sits in recent range
    
    Returns:
        0.0 = at low, 1.0 = at high, 0.5 = mid-range
    """
    try:
        if len(klines) < lookback:
            return None
        
        df = pd.DataFrame(klines[-lookback:], columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['close'] = pd.to_numeric(df['close'])
        
        current_price = df['close'].iloc[-1]
        period_high = df['high'].max()
        period_low = df['low'].min()
        
        if period_high == period_low:
            return 0.5
        
        range_pos = (current_price - period_low) / (period_high - period_low)
        return range_pos
        
    except Exception as e:
        print(f"Error calculating range position: {e}")
        return None
