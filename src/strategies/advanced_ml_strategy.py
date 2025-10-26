"""
Advanced ML Strategy
Uses advanced feature engineering and trained XGBoost/LightGBM models
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import json

from utils.advanced_features import AdvancedFeatureEngine


class AdvancedMLStrategy:
    """
    Advanced ML trading strategy with:
    - 65+ engineered features
    - XGBoost/LightGBM models
    - Feature normalization
    - Market regime awareness
    """
    
    def __init__(self, config, model_monitor=None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.position = None
        self.model_monitor = model_monitor  # Optional model monitoring
        
        # Feature engine
        self.feature_engine = AdvancedFeatureEngine()
        
        # Model components
        self.model = None
        self.scaler = None
        self.selected_features = None
        self.model_metadata = None
        
        # Model paths
        model_dir = Path('models/advanced_ml')
        self.model_path = model_dir / f"{config.symbol}_{config.timeframe}_advanced_ml.joblib"
        self.meta_path = model_dir / f"{config.symbol}_{config.timeframe}_advanced_ml.meta.json"
        self.scaler_path = model_dir / f"{config.symbol}_{config.timeframe}_scaler.joblib"
        
        # Fallback to old models if advanced not available
        if not self.model_path.exists():
            self.logger.warning(f"Advanced model not found at {self.model_path}")
            self.logger.warning("Falling back to basic ML model")
            self._use_fallback = True
            # Import and use old strategy
            from strategies.ml_ema_strategy import MLEMAStrategy
            self.fallback_strategy = MLEMAStrategy(config)
        else:
            self._use_fallback = False
            self._load_model()
    
    def _load_model(self):
        """Load trained model and metadata"""
        try:
            # Load model
            self.model = joblib.load(self.model_path)
            self.logger.info(f"Loaded advanced model from {self.model_path}")
            
            # Load scaler
            if self.scaler_path.exists():
                self.scaler = joblib.load(self.scaler_path)
            
            # Load metadata
            if self.meta_path.exists():
                with open(self.meta_path, 'r') as f:
                    self.model_metadata = json.load(f)
                    self.selected_features = self.model_metadata.get('features', [])
                    
                    self.logger.info(
                        f"Model: {self.model_metadata.get('model_name', 'Unknown')}, "
                        f"F1: {self.model_metadata.get('f1', 0):.3f}, "
                        f"Features: {len(self.selected_features)}"
                    )
        
        except Exception as e:
            self.logger.error(f"Failed to load advanced model: {e}", exc_info=True)
            self.model = None
    
    def analyze(self, klines):
        """
        Analyze market data and generate trading signals
        
        Args:
            klines: Raw kline data from Binance
            
        Returns:
            dict: Trading signal or None
        """
        # Use fallback if advanced model not available
        if self._use_fallback:
            return self.fallback_strategy.analyze(klines)
        
        if self.model is None:
            self.logger.debug("Advanced model not loaded, skipping analysis")
            return None
        
        # Convert klines to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        # Convert to numeric
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        
        # Build advanced features
        try:
            features = self.feature_engine.build_features(df)
            
            if features.empty:
                self.logger.warning("Feature engineering produced no samples")
                return None
            
            # Get latest features
            latest_features = features.iloc[[-1]]
            
            # Select only features used by model
            if self.selected_features:
                # Check if all features are present
                missing_features = set(self.selected_features) - set(latest_features.columns)
                if missing_features:
                    self.logger.warning(f"Missing features: {missing_features}")
                    return None
                
                latest_features = latest_features[self.selected_features]
            
            # Normalize if scaler available
            if self.scaler is not None:
                latest_features_scaled = pd.DataFrame(
                    self.scaler.transform(latest_features),
                    columns=latest_features.columns,
                    index=latest_features.index
                )
            else:
                latest_features_scaled = latest_features
            
            # Get ML prediction
            prediction = self.model.predict(latest_features_scaled)[0]
            
            # Get confidence (probability)
            if hasattr(self.model, 'predict_proba'):
                proba = self.model.predict_proba(latest_features_scaled)[0]
                ml_confidence = float(proba[1])  # Probability of class 1 (BUY)
            else:
                ml_confidence = 0.6 if prediction == 1 else 0.4
            
            # LOG PREDICTION FOR DEBUGGING
            self.logger.debug(
                f"{self.config.symbol}: ML prediction={prediction}, confidence={ml_confidence:.3f} "
                f"(threshold={getattr(self.config, 'ml_proba_threshold', 0.55):.2f})"
            )
            
            # Record prediction for model monitoring
            if self.model_monitor and prediction == 1:  # Only track BUY signals
                self.model_monitor.record_prediction(
                    symbol=self.config.symbol,
                    predicted=prediction,
                    confidence=ml_confidence,
                    actual=None  # Will update when trade closes
                )
            
            current_price = df['close'].iloc[-1]
            
            # Generate signal
            result = None
            
            # BUY signal - only if confidence is high enough
            min_confidence = getattr(self.config, 'ml_proba_threshold', 0.50)  # Lowered from 0.55
            
            if prediction == 1 and ml_confidence >= min_confidence and self.position != 'long':
                # Get market indicators
                market_regime = latest_features.get('regime', pd.Series([1])).iloc[0]
                hurst = latest_features.get('hurst', pd.Series([0.5])).iloc[0]
                rsi = latest_features.get('rsi_14', pd.Series([50])).iloc[0]
                adx = latest_features.get('adx', pd.Series([20])).iloc[0]
                
                # SMART MARKET REGIME FILTER
                # Detect market type and adjust strategy
                is_trending = adx > 25
                is_ranging = adx < 20
                
                # ===== ENTRY QUALITY FILTERS (PREVENT BUYING TOPS) =====
                
                # 1) Block entries near recent highs (buying into resistance) - RELAXED
                recent_high_20 = df['high'].rolling(20).max().iloc[-1]
                distance_from_high = (recent_high_20 - current_price) / current_price
                if distance_from_high < 0.002:  # Within 0.2% of 20-bar high (was 0.5%)
                    self.logger.debug(f"❌ Skipping: Near recent high (${current_price:.2f} vs ${recent_high_20:.2f})")
                    return None
                
                # 2) Require pullback in trending markets (don't chase) - RELAXED
                ema_21 = latest_features.get('ema_21', pd.Series([current_price])).iloc[0]
                price_above_ema = (current_price - ema_21) / current_price
                if is_trending and price_above_ema > 0.015:  # More than 1.5% above EMA21 (was 0.8%)
                    self.logger.debug(f"❌ Skipping: Price too extended from EMA21 ({price_above_ema*100:.2f}%)")
                    return None
                
                # 3) Check bid-ask spread (avoid wide spreads = low liquidity) - DISABLED for now
                # Crypto markets are liquid enough at these volumes
                pass
                
                # 4) Require favorable recent momentum (price moving up, not down) - RELAXED
                recent_bars_green = (df['close'].iloc[-3:] > df['open'].iloc[-3:]).sum()
                if recent_bars_green == 0:  # All 3 bars bearish (was requiring 2/3 green)
                    self.logger.debug(f"❌ Skipping: All recent bars bearish")
                    return None
                
                # 5) Extreme RSI filters - RELAXED
                if rsi > 85:  # Overbought (was 75, now 85)
                    self.logger.debug(f"❌ Skipping: Overbought RSI ({rsi:.1f})")
                    return None
                
                if rsi < 10:  # Extremely oversold (was 15, now 10)
                    self.logger.debug(f"❌ Skipping: Extremely oversold RSI ({rsi:.1f})")
                    return None
                
                # Set regime-specific parameters that will be used by risk manager
                regime_params = {
                    'is_trending': is_trending,
                    'is_ranging': is_ranging,
                    'adx': adx,
                    'suggested_tp_multiplier': 1.5 if is_trending else 1.0,  # Wider TP in trends
                    'suggested_size_multiplier': 1.2 if is_trending else 0.8  # Bigger size in trends
                }
                
                result = {
                    'action': 'BUY',
                    'price': current_price,
                    'reason': f'Advanced ML predicts profitable entry ({ml_confidence*100:.1f}% confidence)',
                    'indicators': {
                        'ml_signal': int(prediction),
                        'ml_confidence': ml_confidence,
                        'rsi': float(rsi),
                        'adx': float(adx),
                        'regime': int(market_regime),
                        'hurst': float(hurst),
                        'model': self.model_metadata.get('model_name', 'Unknown') if self.model_metadata else 'Unknown'
                    },
                    'regime_params': regime_params  # Pass regime info to position sizing
                }
                self.position = 'long'
                self.logger.info(
                    f"🎯 Advanced ML BUY at {current_price:.2f} "
                    f"(conf: {ml_confidence*100:.0f}%, ADX: {adx:.0f}, RSI: {rsi:.0f})"
                )
            
            # SELL signal
            elif prediction == 0 and self.position == 'long':
                result = {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': 'Advanced ML suggests exit',
                    'indicators': {
                        'ml_signal': int(prediction),
                        'ml_confidence': 1 - ml_confidence
                    }
                }
                self.position = None
                self.logger.info(f"💰 Advanced ML SELL at {current_price:.2f}")
            
            return result
        
        except Exception as e:
            self.logger.error(f"Advanced ML analysis failed: {e}", exc_info=True)
            return None
