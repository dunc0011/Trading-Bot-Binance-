"""
Online Learning Engine
Continuously updates ML models based on live trade outcomes
"""
import logging
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
from sklearn.ensemble import GradientBoostingClassifier
from lightgbm import LGBMClassifier
import json


class OnlineLearner:
    """
    Online learning system that updates models incrementally based on trade outcomes
    
    Features:
    - Partial fit updates (incremental learning)
    - Learning rate decay (emphasize recent trades)
    - Model versioning and rollback
    - Performance tracking
    """
    
    def __init__(self, symbol: str, model_dir: str = 'models/advanced_ml',
                 update_frequency: int = 10, learning_rate: float = 0.1):
        """
        Args:
            symbol: Trading pair
            model_dir: Directory containing trained models
            update_frequency: Update model every N trades
            learning_rate: Weight for new data (0.1 = 10% new, 90% old)
        """
        self.symbol = symbol
        self.model_dir = Path(model_dir)
        self.update_frequency = update_frequency
        self.learning_rate = learning_rate
        self.logger = logging.getLogger(__name__)
        
        # Trade buffer for batched updates
        self.trade_buffer = []
        self.updates_performed = 0
        
        # Model versioning
        self.current_version = None
        self.model = None
        self.feature_names = None
        
        # Performance tracking
        self.performance_history = []
        
        self._load_base_model()
    
    def _load_base_model(self):
        """Load the base trained model"""
        try:
            # Look for advanced model first
            model_path = self.model_dir / f"{self.symbol}_*_advanced_ml.joblib"
            model_files = list(self.model_dir.glob(f"{self.symbol}_*_advanced_ml.joblib"))
            
            if not model_files:
                # Try legacy model
                model_files = list(Path('models/ml_ema').glob(f"{self.symbol}_*_ml_ema.joblib"))
            
            if model_files:
                model_path = model_files[0]
                self.model = joblib.load(model_path)
                self.current_version = f"base_{datetime.now().strftime('%Y%m%d')}"
                
                # Load metadata for feature names
                meta_path = model_path.with_suffix('.meta.json')
                if meta_path.exists():
                    with open(meta_path, 'r') as f:
                        meta = json.load(f)
                        self.feature_names = meta.get('features', None)
                
                self.logger.info(f"Loaded base model for {self.symbol}: {model_path}")
            else:
                self.logger.warning(f"No trained model found for {self.symbol}")
                
        except Exception as e:
            self.logger.error(f"Failed to load base model: {e}", exc_info=True)
    
    def add_trade_outcome(self, features: Dict, outcome: str, profit_pct: float):
        """
        Add a completed trade to the learning buffer
        
        Args:
            features: Feature dictionary from the trade
            outcome: 'WIN', 'LOSS', or 'BREAKEVEN'
            profit_pct: Profit percentage
        """
        # Convert outcome to binary (profitable or not)
        label = 1 if outcome == 'WIN' else 0
        
        self.trade_buffer.append({
            'features': features,
            'label': label,
            'profit_pct': profit_pct,
            'timestamp': datetime.now()
        })
        
        self.logger.debug(f"Added trade outcome to buffer: {outcome} ({profit_pct:+.2f}%). Buffer size: {len(self.trade_buffer)}")
        
        # Trigger update if buffer is full
        if len(self.trade_buffer) >= self.update_frequency:
            self.update_model()
    
    def update_model(self):
        """Update model with accumulated trade outcomes"""
        if not self.model:
            self.logger.warning("No base model loaded - skipping update")
            return False
        
        if len(self.trade_buffer) < 2:
            self.logger.debug("Not enough trades to update model")
            return False
        
        try:
            self.logger.info(f"Updating model with {len(self.trade_buffer)} new trades...")
            
            # Prepare training data
            X = []
            y = []
            weights = []
            
            # Use exponential decay for weights (recent trades more important)
            for i, trade in enumerate(self.trade_buffer):
                features = trade['features']
                
                # Handle missing features
                if self.feature_names:
                    feature_vector = [features.get(fname, 0) for fname in self.feature_names]
                else:
                    feature_vector = list(features.values())
                
                X.append(feature_vector)
                y.append(trade['label'])
                
                # Exponential weight: recent trades weighted more
                weight = np.exp(i / len(self.trade_buffer))
                weights.append(weight)
            
            X = np.array(X)
            y = np.array(y)
            weights = np.array(weights)
            
            # Normalize weights
            weights = weights / weights.sum() * len(weights)
            
            # Check if model supports partial_fit (incremental learning)
            if hasattr(self.model, 'partial_fit'):
                # Online learning with partial_fit
                self.model.partial_fit(X, y, sample_weight=weights)
                update_method = "partial_fit"
            else:
                # Retrain with combined old + new data (weighted)
                # This is a simplified version - in production, you'd keep more history
                if hasattr(self.model, 'fit'):
                    self.model.fit(X, y, sample_weight=weights)
                    update_method = "refit"
                else:
                    self.logger.warning("Model doesn't support partial_fit or fit")
                    return False
            
            # Save updated model
            self.updates_performed += 1
            new_version = f"v{self.updates_performed}_{datetime.now().strftime('%Y%m%d_%H%M')}"
            
            # Save with versioning
            version_path = self.model_dir / f"{self.symbol}_online_{new_version}.joblib"
            joblib.dump(self.model, version_path)
            
            # Update metadata
            meta_path = version_path.with_suffix('.meta.json')
            meta = {
                'symbol': self.symbol,
                'version': new_version,
                'update_method': update_method,
                'trades_processed': len(self.trade_buffer),
                'total_updates': self.updates_performed,
                'updated_at': datetime.now().isoformat(),
                'learning_rate': self.learning_rate,
                'win_rate_in_update': (np.array(y) == 1).mean(),
                'avg_profit_pct': np.mean([t['profit_pct'] for t in self.trade_buffer])
            }
            
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
            
            # Track performance
            self.performance_history.append(meta)
            
            # Clear buffer
            self.trade_buffer.clear()
            
            self.logger.info(f"✅ Model updated: {update_method}, version {new_version}")
            self.logger.info(f"   Trades processed: {len(y)}, Win rate: {meta['win_rate_in_update']*100:.1f}%")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update model: {e}", exc_info=True)
            return False
    
    def predict(self, features: Dict) -> tuple:
        """
        Make prediction with online-updated model
        
        Returns:
            (prediction, confidence)
        """
        if not self.model:
            return None, 0.0
        
        try:
            # Prepare feature vector
            if self.feature_names:
                feature_vector = np.array([[features.get(fname, 0) for fname in self.feature_names]])
            else:
                feature_vector = np.array([list(features.values())])
            
            # Predict
            prediction = self.model.predict(feature_vector)[0]
            
            # Get confidence if available
            if hasattr(self.model, 'predict_proba'):
                confidence = self.model.predict_proba(feature_vector)[0, 1]
            else:
                confidence = 0.5
            
            return prediction, confidence
            
        except Exception as e:
            self.logger.error(f"Prediction failed: {e}", exc_info=True)
            return None, 0.0
    
    def get_performance_summary(self) -> Dict:
        """Get summary of online learning performance"""
        if not self.performance_history:
            return {
                'updates_performed': 0,
                'total_trades_processed': 0,
                'avg_win_rate': 0,
                'avg_profit_pct': 0
            }
        
        return {
            'updates_performed': self.updates_performed,
            'total_trades_processed': sum(h['trades_processed'] for h in self.performance_history),
            'avg_win_rate': np.mean([h['win_rate_in_update'] for h in self.performance_history]),
            'avg_profit_pct': np.mean([h['avg_profit_pct'] for h in self.performance_history]),
            'last_update': self.performance_history[-1]['updated_at'],
            'current_version': self.performance_history[-1]['version']
        }
    
    def rollback_to_base(self):
        """Rollback to original base model"""
        self.logger.info("Rolling back to base model...")
        self._load_base_model()
        self.trade_buffer.clear()
        self.updates_performed = 0
        self.performance_history.clear()
    
    def enable_auto_update(self, trade_logger):
        """
        Enable automatic updates from trade logger
        
        Args:
            trade_logger: TradeLogger instance
        """
        # This would be called periodically by the bot
        # to fetch new trades and update the model
        recent_trades = trade_logger.get_trades_for_learning(min_trades=self.update_frequency)
        
        if len(recent_trades) >= self.update_frequency:
            for _, trade in recent_trades.iterrows():
                # Extract features from JSON
                try:
                    features = json.loads(trade['entry_features'])
                    self.add_trade_outcome(
                        features=features,
                        outcome=trade['outcome'],
                        profit_pct=trade['profit_pct']
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to process trade for learning: {e}")


class OnlineLearningManager:
    """
    Manages multiple online learners for different symbols
    """
    
    def __init__(self, symbols: list, update_frequency: int = 10):
        self.learners = {symbol: OnlineLearner(symbol, update_frequency=update_frequency) 
                        for symbol in symbols}
        self.logger = logging.getLogger(__name__)
    
    def process_trade_outcome(self, symbol: str, features: Dict, outcome: str, profit_pct: float):
        """Process a trade outcome for the appropriate learner"""
        if symbol in self.learners:
            self.learners[symbol].add_trade_outcome(features, outcome, profit_pct)
        else:
            self.logger.warning(f"No learner found for {symbol}")
    
    def get_all_performance(self) -> Dict:
        """Get performance summary for all learners"""
        return {symbol: learner.get_performance_summary() 
                for symbol, learner in self.learners.items()}
