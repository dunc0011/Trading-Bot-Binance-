"""
Fast Scalping Strategy
Aggressive strategy for frequent small trades using RSI + EMA
"""
import logging
import pandas as pd
import numpy as np


class ScalpingStrategy:
    """
    Fast scalping strategy:
    - BUY: RSI < 35 AND price below EMA5
    - SELL: RSI > 65 OR 0.3% profit
    - Very frequent signals for active trading
    """
    
    def __init__(self, config, model_monitor=None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.position = None
        self.entry_price = None
        self.model_monitor = model_monitor
        
        # Scalping parameters
        self.rsi_oversold = 35  # More aggressive than 30
        self.rsi_overbought = 65  # More aggressive than 70
        self.quick_profit_target = 0.003  # 0.3% quick profit
    
    def _calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator"""
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def analyze(self, klines):
        """
        Analyze market and generate scalping signals
        
        Args:
            klines: List of kline data from Binance
            
        Returns:
            Signal dict or None
        """
        try:
            # Convert to DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            if len(df) < 20:
                return None
            
            # Calculate indicators
            df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
            df['ema8'] = df['close'].ewm(span=8, adjust=False).mean()
            df['rsi'] = self._calculate_rsi(df['close'], period=14)
            
            # Get latest values
            current_price = df['close'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema5 = df['ema5'].iloc[-1]
            ema8 = df['ema8'].iloc[-1]
            
            # Check for NaN
            if pd.isna(rsi) or pd.isna(ema5):
                return None
            
            # BUY SIGNAL: Oversold + below EMA
            if self.position is None:
                if rsi < self.rsi_oversold and current_price < ema5:
                    self.position = 'long'
                    self.entry_price = current_price
                    
                    self.logger.info(
                        f"🚀 SCALP BUY at {current_price:.2f} "
                        f"(RSI: {rsi:.0f}, below EMA5: ${ema5:.2f})"
                    )
                    
                    return {
                        'action': 'BUY',
                        'price': current_price,
                        'reason': f'Scalp entry: RSI {rsi:.0f} oversold',
                        'indicators': {
                            'rsi': float(rsi),
                            'ema5': float(ema5),
                            'ema8': float(ema8),
                            'ml_confidence': 0.6  # Simulated for compatibility
                        }
                    }
            
            # SELL SIGNAL: Overbought OR quick profit
            elif self.position == 'long' and self.entry_price:
                profit_pct = (current_price - self.entry_price) / self.entry_price
                
                # Quick profit target hit
                if profit_pct >= self.quick_profit_target:
                    self.position = None
                    self.logger.info(
                        f"💰 SCALP SELL at {current_price:.2f} "
                        f"(Quick profit: +{profit_pct*100:.2f}%)"
                    )
                    
                    return {
                        'action': 'SELL',
                        'price': current_price,
                        'reason': f'Quick profit target ({profit_pct*100:.2f}%)',
                        'indicators': {'rsi': float(rsi)}
                    }
                
                # RSI overbought
                elif rsi > self.rsi_overbought:
                    self.position = None
                    self.logger.info(
                        f"💰 SCALP SELL at {current_price:.2f} "
                        f"(RSI overbought: {rsi:.0f})"
                    )
                    
                    return {
                        'action': 'SELL',
                        'price': current_price,
                        'reason': f'RSI overbought ({rsi:.0f})',
                        'indicators': {'rsi': float(rsi)}
                    }
                
                # Stop loss: -0.5%
                elif profit_pct < -0.005:
                    self.position = None
                    self.logger.warning(
                        f"🛑 SCALP STOP at {current_price:.2f} "
                        f"(Loss: {profit_pct*100:.2f}%)"
                    )
                    
                    return {
                        'action': 'SELL',
                        'price': current_price,
                        'reason': f'Stop loss ({profit_pct*100:.2f}%)',
                        'indicators': {'rsi': float(rsi)}
                    }
            
            return None
        
        except Exception as e:
            self.logger.error(f"Scalping analysis failed: {e}", exc_info=True)
            return None
