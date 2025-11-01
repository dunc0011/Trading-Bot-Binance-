"""
Meta-Learning Ensemble Optimizer

Trains a second-level AI that learns:
- When to trust the primary ML models
- Optimal portfolio allocation
- Risk adjustment based on market regime
- Signal filtering and enhancement
"""
import logging
import numpy as np
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
import joblib

logger = logging.getLogger(__name__)


class EnsembleOptimizer:
    """Meta-learner that optimizes across all primary models."""
    
    def __init__(self, db_path: str = 'data/performance.db'):
        self.db_path = db_path
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = []
        self.is_trained = False
        self.model_path = Path('models/meta_learning/ensemble_optimizer.joblib')
        
        # Try to load existing model
        self._load_model()
    
    def should_take_signal(self, signal_context: Dict) -> Dict:
        """
        Meta-decision: should we take this signal?
        
        Returns dict with:
        - take_signal: bool
        - confidence_boost: float (adjustment to apply)
        - reason: str
        """
        if not self.is_trained:
            # Not trained yet - allow all signals
            return {'take_signal': True, 'confidence_boost': 0, 'reason': 'Meta-learner not trained'}
        
        try:
            # Extract features from signal context
            features = self._extract_features(signal_context)
            
            if features is None:
                return {'take_signal': True, 'confidence_boost': 0, 'reason': 'Insufficient context'}
            
            # Get prediction
            X = np.array([features])
            X_scaled = self.scaler.transform(X)
            
            prediction = self.model.predict(X_scaled)[0]
            probability = self.model.predict_proba(X_scaled)[0]
            
            confidence = probability[prediction]
            
            # Decision logic
            if prediction == 1 and confidence > 0.60:
                # Meta-learner approves
                boost = (confidence - 0.5) * 0.1  # Up to +5% boost
                return {
                    'take_signal': True,
                    'confidence_boost': boost,
                    'reason': f'Meta-approved ({confidence:.1%} confidence)'
                }
            elif prediction == 0 and confidence > 0.65:
                # Meta-learner rejects
                return {
                    'take_signal': False,
                    'confidence_boost': 0,
                    'reason': f'Meta-filtered ({confidence:.1%} probability of loss)'
                }
            else:
                # Uncertain - allow but no boost
                return {
                    'take_signal': True,
                    'confidence_boost': 0,
                    'reason': 'Meta-learner uncertain'
                }
        
        except Exception as e:
            logger.error(f"Meta-decision error: {e}")
            return {'take_signal': True, 'confidence_boost': 0, 'reason': 'Error in meta-learner'}
    
    def train(self, min_samples: int = 50):
        """Train the meta-learner on historical performance."""
        import sqlite3
        
        logger.info("🧠 Training meta-learner...")
        
        try:
            # Load training data from database
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT 
                        symbol, ml_confidence, market_regime, volatility,
                        volume_24h, rsi, trend_strength, hour_of_day,
                        day_of_week, pnl_pct
                    FROM trades
                    WHERE ml_confidence IS NOT NULL
                        AND exit_time >= datetime('now', '-60 days')
                    ORDER BY exit_time DESC
                ''')
                
                rows = cursor.fetchall()
            
            if len(rows) < min_samples:
                logger.warning(f"Insufficient data for meta-training: {len(rows)} < {min_samples}")
                return False
            
            # Prepare dataset
            X_list = []
            y_list = []
            
            for row in rows:
                features = self._extract_features(dict(row))
                if features is not None:
                    X_list.append(features)
                    # Binary label: 1 if profitable, 0 if not
                    y_list.append(1 if row['pnl_pct'] > 0 else 0)
            
            if len(X_list) < min_samples:
                logger.warning(f"Insufficient valid samples: {len(X_list)}")
                return False
            
            X = np.array(X_list)
            y = np.array(y_list)
            
            # Scale features
            X_scaled = self.scaler.fit_transform(X)
            
            # Train ensemble model
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                random_state=42
            )
            
            self.model.fit(X_scaled, y)
            
            # Evaluate
            train_acc = self.model.score(X_scaled, y)
            logger.info(f"✅ Meta-learner trained on {len(X)} samples | Accuracy: {train_acc:.2%}")
            
            self.is_trained = True
            self._save_model()
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to train meta-learner: {e}", exc_info=True)
            return False
    
    def _extract_features(self, context: Dict) -> Optional[List[float]]:
        """Extract feature vector from signal context."""
        try:
            # Define feature extraction
            features = [
                float(context.get('ml_confidence', 0.5)),
                float(context.get('volatility', 0)),
                float(context.get('volume_24h', 0)) / 1e9,  # Normalize to billions
                float(context.get('rsi', 50)) / 100,  # Normalize to 0-1
                float(context.get('trend_strength', 0)),
                float(context.get('hour_of_day', 12)) / 24,  # Normalize to 0-1
                float(context.get('day_of_week', 3)) / 7,  # Normalize to 0-1
                # Regime one-hot encoding
                1 if context.get('market_regime') == 'trending' else 0,
                1 if context.get('market_regime') == 'ranging' else 0,
                1 if context.get('market_regime') == 'volatile' else 0,
            ]
            
            # Store feature names for interpretability
            if not self.feature_names:
                self.feature_names = [
                    'ml_confidence', 'volatility', 'volume_24h', 'rsi',
                    'trend_strength', 'hour_of_day', 'day_of_week',
                    'regime_trending', 'regime_ranging', 'regime_volatile'
                ]
            
            return features
        
        except Exception as e:
            logger.debug(f"Feature extraction error: {e}")
            return None
    
    def get_feature_importance(self) -> Dict:
        """Get feature importance scores from trained model."""
        if not self.is_trained or not hasattr(self.model, 'feature_importances_'):
            return {}
        
        importances = self.model.feature_importances_
        return dict(zip(self.feature_names, importances))
    
    def _save_model(self):
        """Save trained model to disk."""
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            
            model_data = {
                'model': self.model,
                'scaler': self.scaler,
                'feature_names': self.feature_names,
                'trained_at': datetime.now().isoformat()
            }
            
            joblib.dump(model_data, self.model_path)
            logger.info(f"💾 Meta-learner saved to {self.model_path}")
        
        except Exception as e:
            logger.error(f"Failed to save meta-learner: {e}")
    
    def _load_model(self):
        """Load trained model from disk."""
        if self.model_path.exists():
            try:
                model_data = joblib.load(self.model_path)
                self.model = model_data['model']
                self.scaler = model_data['scaler']
                self.feature_names = model_data['feature_names']
                self.is_trained = True
                logger.info(f"📥 Meta-learner loaded from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load meta-learner: {e}")
