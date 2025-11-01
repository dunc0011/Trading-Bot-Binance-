"""
Mean Reversion Strategy - ML predicts bounce quality at extremes

Strategy:
1. Wait for oversold (RSI<30, price at lower BB) or overbought (RSI>70, upper BB)
2. ML predicts: "Will this extreme reverse and bounce 2-5%?"
3. Enter on predicted bounces, exit at mean reversion completion

Features ML learns from:
- RSI extremes and momentum
- Bollinger Band position
- Volume spikes (confirmation)
- MACD histogram (momentum shift)
- Support/resistance context
- Volatility regime
"""
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict
import joblib
import json

logger = logging.getLogger(__name__)


class MeanReversionStrategy:
    """ML-powered mean reversion strategy"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.symbol = config.symbol
        self.timeframe = config.timeframe
        
        # Position tracking
        self.position = None
        
        # Load trained model
        self.model = None
        self.model_metadata = None
        self._load_model()
    
    def _load_model(self):
        """Load trained mean reversion ML model"""
        model_dir = Path(getattr(self.config, 'mr_model_dir', 'models/mean_reversion'))
        model_file = model_dir / f"{self.symbol}_{self.timeframe}_mean_reversion.joblib"
        meta_file = model_dir / f"{self.symbol}_{self.timeframe}_mean_reversion.meta.json"
        
        if not model_file.exists():
            self.logger.warning(f"No trained model found for {self.symbol} {self.timeframe}")
            return
        
        try:
            self.model = joblib.load(model_file)
            
            if meta_file.exists():
                with open(meta_file, 'r') as f:
                    self.model_metadata = json.load(f)
                
                f1 = self.model_metadata.get('f1', 0)
                self.logger.info(f"🔄 Loaded mean reversion model: {self.symbol}_{self.timeframe} | F1={f1:.3f}")
            else:
                self.logger.info(f"✅ Loaded mean reversion model: {self.symbol}_{self.timeframe}")
        
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}", exc_info=True)
    
    def _calculate_features(self, df: pd.DataFrame) -> Optional[pd.Series]:
        """Calculate mean reversion features"""
        if len(df) < 50:
            return None
        
        try:
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            # Bollinger Bands
            sma_20 = df['close'].rolling(20).mean()
            std_20 = df['close'].rolling(20).std()
            bb_upper = sma_20 + (2 * std_20)
            bb_lower = sma_20 - (2 * std_20)
            bb_position = (df['close'] - bb_lower) / (bb_upper - bb_lower)
            
            # Volume
            volume_sma = df['volume'].rolling(20).mean()
            volume_ratio = df['volume'] / volume_sma
            
            # MACD
            ema_12 = df['close'].ewm(span=12).mean()
            ema_26 = df['close'].ewm(span=26).mean()
            macd = ema_12 - ema_26
            macd_signal = macd.ewm(span=9).mean()
            macd_hist = macd - macd_signal
            
            # ATR (volatility)
            high_low = df['high'] - df['low']
            high_close = (df['high'] - df['close'].shift()).abs()
            low_close = (df['low'] - df['close'].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            atr_pct = atr / df['close']
            
            # Price momentum
            returns_1 = df['close'].pct_change(1)
            returns_5 = df['close'].pct_change(5)
            
            # Support/Resistance context
            recent_high = df['high'].rolling(20).max()
            recent_low = df['low'].rolling(20).min()
            price_range_position = (df['close'] - recent_low) / (recent_high - recent_low)
            
            # Enhanced features - Multiple RSI periods
            delta = df['close'].diff()
            rsi_21 = None
            rsi_28 = None
            for period in [21, 28]:
                gain = (delta.where(delta > 0, 0)).rolling(period).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
                rs = gain / loss
                rsi_period = 100 - (100 / (1 + rs))
                if period == 21:
                    rsi_21 = rsi_period
                else:
                    rsi_28 = rsi_period
            
            # Volume surge and trends
            volume_surge = df['volume'] / df['volume'].rolling(50).mean()
            volume_trend = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
            
            # Volatility regime
            volatility_regime = atr_pct / atr_pct.rolling(50).mean()
            
            # Multi-period returns
            returns_10 = df['close'].pct_change(10)
            returns_20 = df['close'].pct_change(20)
            
            # Build enhanced feature vector
            features = pd.Series({
                'rsi': rsi.iloc[-1],
                'rsi_momentum': rsi.diff(1).iloc[-1],
                'rsi_21': rsi_21.iloc[-1] if rsi_21 is not None else rsi.iloc[-1],
                'rsi_28': rsi_28.iloc[-1] if rsi_28 is not None else rsi.iloc[-1],
                'bb_position': bb_position.iloc[-1],
                'bb_width': ((bb_upper - bb_lower) / sma_20).iloc[-1],
                'volume_ratio': volume_ratio.iloc[-1],
                'volume_surge': volume_surge.iloc[-1],
                'volume_trend': volume_trend.iloc[-1],
                'macd_hist': macd_hist.iloc[-1],
                'macd_hist_change': macd_hist.diff(1).iloc[-1],
                'atr_pct': atr_pct.iloc[-1],
                'volatility_regime': volatility_regime.iloc[-1],
                'returns_1': returns_1.iloc[-1],
                'returns_5': returns_5.iloc[-1],
                'returns_10': returns_10.iloc[-1],
                'returns_20': returns_20.iloc[-1],
                'price_range_position': price_range_position.iloc[-1],
                'distance_to_high': (recent_high.iloc[-1] - df['close'].iloc[-1]) / df['close'].iloc[-1],
                'distance_to_low': (df['close'].iloc[-1] - recent_low.iloc[-1]) / df['close'].iloc[-1],
            })
            
            return features
        
        except Exception as e:
            self.logger.error(f"Feature calculation error: {e}", exc_info=True)
            return None
    
    def analyze(self, klines: list) -> Optional[Dict]:
        """
        Analyze market for mean reversion opportunities
        
        Args:
            klines: List of kline data from Binance
            
        Returns:
            Signal dict or None
        """
        if self.model is None:
            return None
        
        try:
            # Convert to DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'num_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            # Calculate features
            features = self._calculate_features(df)
            
            if features is None or features.isnull().any():
                return None
            
            current_price = float(df['close'].iloc[-1])
            rsi = features['rsi']
            bb_position = features['bb_position']
            
            # Only trade at extremes
            is_oversold = rsi < 30 and bb_position < 0.2  # RSI<30 and near lower BB
            is_overbought = rsi > 70 and bb_position > 0.8  # RSI>70 and near upper BB
            
            if not (is_oversold or is_overbought):
                return None  # Wait for extremes
            
            # ML prediction: will this extreme bounce?
            features_array = features.values.reshape(1, -1)
            prediction = self.model.predict(features_array)[0]
            
            if hasattr(self.model, 'predict_proba'):
                proba = self.model.predict_proba(features_array)[0]
                confidence = proba[1] if len(proba) > 1 else proba[0]
            else:
                confidence = 0.60  # Default for non-probabilistic models
            
            # Generate signals based on ML prediction
            if prediction == 1:  # ML predicts successful bounce
                if is_oversold and self.position is None:
                    # BUY at oversold
                    return {
                        'action': 'BUY',
                        'price': current_price,
                        'reason': f'Mean reversion BUY: RSI={rsi:.1f}, BB={bb_position:.2f} (oversold bounce predicted)',
                        'confidence': float(confidence),
                        'indicators': {
                            'strategy': 'mean_reversion',
                            'ml_confidence': float(confidence),
                            'rsi': float(rsi),
                            'bb_position': float(bb_position),
                            'extreme_type': 'oversold'
                        }
                    }
                
                elif is_overbought and self.position is not None:
                    # SELL at overbought (if we're in position from previous oversold)
                    return {
                        'action': 'SELL',
                        'price': current_price,
                        'reason': f'Mean reversion SELL: RSI={rsi:.1f}, BB={bb_position:.2f} (overbought reached)',
                        'confidence': float(confidence),
                        'indicators': {
                            'strategy': 'mean_reversion',
                            'ml_confidence': float(confidence),
                            'rsi': float(rsi),
                            'bb_position': float(bb_position),
                            'extreme_type': 'overbought'
                        }
                    }
            
            # Also exit if back to mean
            if self.position is not None and 0.4 < bb_position < 0.6:
                # Price returned to middle of BB - mean reversion complete
                return {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': f'Mean reversion complete: BB={bb_position:.2f} (price returned to mean)',
                    'confidence': 0.75,
                    'indicators': {
                        'strategy': 'mean_reversion',
                        'ml_confidence': 0.75,
                        'rsi': float(rsi),
                        'bb_position': float(bb_position),
                        'exit_reason': 'mean_reversion_complete'
                    }
                }
            
            return None
        
        except Exception as e:
            self.logger.error(f"Analysis error: {e}", exc_info=True)
            return None
