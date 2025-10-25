"""
Machine Learning EMA Strategy
Uses ML model to predict profitable EMA crossovers
"""
import logging
import pandas as pd

from utils.ml_model_manager import MLModelManager


class MLEMAStrategy:
    """ML-based trading strategy using EMA and technical indicators"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.position = None  # Track current position
        
        # Initialize ML Model Manager
        model_dir = getattr(config, 'ml_model_dir', 'models/ml_ema')
        self.ml_manager = MLModelManager(
            config=config,
            model_dir=model_dir,
            symbol=config.symbol,
            interval=config.timeframe,
            logger=self.logger
        )
        
        # Load or train model
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize ML model - load from disk or indicate training needed"""
        self.ml_manager.ensure_loaded()
        
        if self.ml_manager._model is None:
            self.logger.warning(
                "No trained model found. Please train a model first using:\n"
                "  python -m src.utils.train_ml_model"
            )
    
    def analyze(self, klines):
        """
        Analyze market data and generate trading signals using ML model
        
        Args:
            klines: Raw kline data from Binance
            
        Returns:
            dict: Trading signal or None
        """
        # Check if model is loaded
        if self.ml_manager._model is None:
            self.logger.debug("ML model not loaded, skipping analysis")
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
        
        # Build features (without target)
        X, _ = self.ml_manager.build_features(df)
        
        if X.empty:
            self.logger.warning("Feature engineering produced no samples")
            return None
        
        # Get latest features
        latest_features = X.iloc[[-1]]
        current_price = df['close'].iloc[-1]
        
        # Get ML prediction
        try:
            signal = self.ml_manager.predict_signal(latest_features)
        except Exception as e:
            self.logger.error(f"ML prediction failed: {e}", exc_info=True)
            return None
        
        # Generate trading signal
        result = None
        
        # BUY signal
        if signal == 1 and self.position != 'long':
            result = {
                'action': 'BUY',
                'price': current_price,
                'reason': 'ML model predicts profitable long entry',
                'indicators': {
                    'ema5': float(latest_features['ema5'].iloc[0]),
                    'ema8': float(latest_features['ema8'].iloc[0]),
                    'rsi': float(latest_features['rsi'].iloc[0]),
                    'ml_signal': signal
                }
            }
            self.position = 'long'
            self.logger.info(f"ML BUY signal generated at {current_price}")
        
        # SELL signal (exit long position)
        elif signal == 0 and self.position == 'long':
            result = {
                'action': 'SELL',
                'price': current_price,
                'reason': 'ML model suggests exiting long position',
                'indicators': {
                    'ema5': float(latest_features['ema5'].iloc[0]),
                    'ema8': float(latest_features['ema8'].iloc[0]),
                    'rsi': float(latest_features['rsi'].iloc[0]),
                    'ml_signal': signal
                }
            }
            self.position = None
            self.logger.info(f"ML SELL signal generated at {current_price}")
        
        return result
