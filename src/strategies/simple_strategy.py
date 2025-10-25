"""
Simple Moving Average Crossover Strategy
"""
import pandas as pd
import logging


class SimpleStrategy:
    """Simple SMA crossover strategy for demonstration."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.position = None  # Track current position
        
        # Strategy parameters
        self.fast_period = 10
        self.slow_period = 30
    
    def analyze(self, klines):
        """
        Analyze market data and generate trading signals.
        
        Args:
            klines: Raw kline data from Binance
            
        Returns:
            dict: Trading signal or None
        """
        # Convert klines to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        # Convert to numeric
        df['close'] = pd.to_numeric(df['close'])
        
        # Calculate SMAs
        df['sma_fast'] = df['close'].rolling(window=self.fast_period).mean()
        df['sma_slow'] = df['close'].rolling(window=self.slow_period).mean()
        
        # Get latest values
        current_price = df['close'].iloc[-1]
        sma_fast = df['sma_fast'].iloc[-1]
        sma_slow = df['sma_slow'].iloc[-1]
        
        prev_sma_fast = df['sma_fast'].iloc[-2]
        prev_sma_slow = df['sma_slow'].iloc[-2]
        
        # Generate signals
        signal = None
        
        # Bullish crossover
        if prev_sma_fast <= prev_sma_slow and sma_fast > sma_slow:
            if self.position != 'long':
                signal = {
                    'action': 'BUY',
                    'price': current_price,
                    'reason': 'SMA bullish crossover',
                    'indicators': {
                        'sma_fast': sma_fast,
                        'sma_slow': sma_slow
                    }
                }
                self.position = 'long'
        
        # Bearish crossover
        elif prev_sma_fast >= prev_sma_slow and sma_fast < sma_slow:
            if self.position == 'long':
                signal = {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': 'SMA bearish crossover',
                    'indicators': {
                        'sma_fast': sma_fast,
                        'sma_slow': sma_slow
                    }
                }
                self.position = None
        
        return signal
