"""
Meta-Learning Signal Filter
Learns WHEN to take trades based on historical outcomes and market context
"""
import logging
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import json


class MetaLearner:
    """
    Meta-learning model that filters base model signals
    
    Learns: "Given base model signal + market context, will this trade be profitable?"
    
    Features used:
    - Base model confidence
    - Market regime (trending/ranging/volatile)
    - Volume context (surge, buy/sell ratio)
    - Recent performance (win streak, recent win rate)
    - Similar trade history
    - Time-based patterns
    """
    
    def __init__(self, trade_logger, min_trades_for_training: int = 50,
                 retrain_frequency: int = 50, confidence_threshold: float = 0.65):
        """
        Args:
            trade_logger: TradeLogger instance for accessing trade history
            min_trades_for_training: Minimum trades needed before first training
            retrain_frequency: Retrain every N new trades
            confidence_threshold: Minimum meta-confidence to take trade
        """
        self.trade_logger = trade_logger
        self.min_trades_for_training = min_trades_for_training
        self.retrain_frequency = retrain_frequency
        self.confidence_threshold = confidence_threshold
        self.logger = logging.getLogger(__name__)
        
        # Model state
        self.model = None
        self.feature_names = []
        self.is_trained = False
        self.trades_since_retrain = 0
        self.training_history = []
        
        # Performance tracking
        self.recent_decisions = []  # Track recent filter decisions
        
        # Model save path
        self.model_dir = Path('models/meta_learning')
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Try to load existing model
        self._load_model()
    
    def _load_model(self):
        """Load existing meta-learner model if available"""
        model_path = self.model_dir / 'meta_learner.joblib'
        if model_path.exists():
            try:
                self.model = joblib.load(model_path)
                
                # Load metadata
                meta_path = model_path.with_suffix('.meta.json')
                if meta_path.exists():
                    with open(meta_path, 'r') as f:
                        meta = json.load(f)
                        self.feature_names = meta.get('features', [])
                        self.is_trained = True
                
                self.logger.info(f"Loaded existing meta-learner model")
            except Exception as e:
                self.logger.warning(f"Failed to load meta-learner: {e}")
    
    def _build_meta_features(self, base_signal: Dict, trade_history: pd.DataFrame) -> Dict:
        """
        Build meta-learning features from base signal and context
        
        Args:
            base_signal: Signal from base model with confidence, indicators
            trade_history: Recent trade history for context
            
        Returns:
            Dictionary of meta-features
        """
        features = {}
        
        # === Base Model Features ===
        features['base_confidence'] = base_signal.get('confidence', 0.5)
        features['signal_strength'] = base_signal.get('signal_strength', 0)
        
        # === Market Regime Features ===
        indicators = base_signal.get('indicators', {})
        features['regime_trending'] = 1 if indicators.get('adx', 0) > 25 else 0
        features['regime_ranging'] = 1 if indicators.get('adx', 0) < 20 else 0
        features['regime_volatile'] = indicators.get('regime_volatile', 0)
        
        # === Trend Alignment ===
        features['h1_trend'] = indicators.get('h1_trend', 0)
        features['trend_confluence'] = indicators.get('trend_confluence', 0)
        
        # === Volume Context ===
        features['volume_surge'] = indicators.get('volume_surge', 1.0)
        features['buy_sell_ratio'] = indicators.get('buy_sell_ratio', 1.0)
        features['vwap_distance'] = indicators.get('vwap_dist', 0)
        
        # === Technical Indicators ===
        features['rsi'] = indicators.get('rsi', 50)
        features['rsi_overbought'] = 1 if indicators.get('rsi', 50) > 70 else 0
        features['rsi_oversold'] = 1 if indicators.get('rsi', 50) < 30 else 0
        features['atr_pct'] = indicators.get('atr_pct', 0)
        
        # === Recent Performance Context ===
        if len(trade_history) > 0:
            # Recent trades (last 20)
            recent = trade_history.head(20)
            
            # Win rate
            if len(recent) > 0:
                features['recent_win_rate'] = (recent['outcome'] == 'WIN').mean()
                features['recent_avg_profit'] = recent['profit_pct'].mean()
                features['recent_trades_count'] = len(recent)
                
                # Win/loss streak
                last_5 = recent.head(5)
                features['win_streak'] = (last_5['outcome'] == 'WIN').sum()
                features['loss_streak'] = (last_5['outcome'] == 'LOSS').sum()
            else:
                features['recent_win_rate'] = 0.5
                features['recent_avg_profit'] = 0
                features['recent_trades_count'] = 0
                features['win_streak'] = 0
                features['loss_streak'] = 0
            
            # === Similar Trade Success Rate ===
            # Find trades with similar confidence
            confidence = features['base_confidence']
            similar_conf = trade_history[
                (trade_history['ml_confidence'] >= confidence - 0.05) &
                (trade_history['ml_confidence'] <= confidence + 0.05)
            ]
            
            if len(similar_conf) >= 5:
                features['similar_trade_win_rate'] = (similar_conf['outcome'] == 'WIN').mean()
                features['similar_trade_count'] = len(similar_conf)
            else:
                features['similar_trade_win_rate'] = 0.5
                features['similar_trade_count'] = 0
            
            # === Regime-Specific Success ===
            # How well do we do in this regime?
            if features['regime_trending']:
                regime_trades = trade_history[trade_history['regime_trending'] == 1]
                if len(regime_trades) >= 5:
                    features['regime_win_rate'] = (regime_trades['outcome'] == 'WIN').mean()
                else:
                    features['regime_win_rate'] = 0.5
            elif features['regime_ranging']:
                regime_trades = trade_history[trade_history['regime_ranging'] == 1]
                if len(regime_trades) >= 5:
                    features['regime_win_rate'] = (regime_trades['outcome'] == 'WIN').mean()
                else:
                    features['regime_win_rate'] = 0.5
            else:
                features['regime_win_rate'] = 0.5
        else:
            # No history - use neutral values
            features['recent_win_rate'] = 0.5
            features['recent_avg_profit'] = 0
            features['recent_trades_count'] = 0
            features['win_streak'] = 0
            features['loss_streak'] = 0
            features['similar_trade_win_rate'] = 0.5
            features['similar_trade_count'] = 0
            features['regime_win_rate'] = 0.5
        
        # === Time-Based Features ===
        now = datetime.now()
        features['hour_of_day'] = now.hour
        features['day_of_week'] = now.weekday()
        features['is_weekend'] = 1 if now.weekday() >= 5 else 0
        
        # Normalized time features (cyclical)
        features['hour_sin'] = np.sin(2 * np.pi * now.hour / 24)
        features['hour_cos'] = np.cos(2 * np.pi * now.hour / 24)
        
        return features
    
    def train(self, force: bool = False):
        """
        Train meta-learner on historical trade data
        
        Args:
            force: Force retraining even if not enough new trades
        """
        # Check if we have enough trades
        stats = self.trade_logger.get_stats()
        total_trades = stats['total_trades']
        
        if total_trades < self.min_trades_for_training:
            self.logger.info(f"Not enough trades for meta-learning yet ({total_trades}/{self.min_trades_for_training})")
            return False
        
        if not force and self.trades_since_retrain < self.retrain_frequency:
            return False
        
        try:
            self.logger.info(f"Training meta-learner on {total_trades} trades...")
            
            # Get all completed trades
            trades_df = self.trade_logger.get_recent_trades(limit=1000)
            trades_df = trades_df[trades_df['exit_time'].notna()].copy()
            
            if len(trades_df) < self.min_trades_for_training:
                self.logger.warning("Not enough completed trades")
                return False
            
            # Build features for each trade
            X = []
            y = []
            
            for idx, trade in trades_df.iterrows():
                # Build meta-features as they would have been at entry time
                # Get trade history up to that point
                entry_time = pd.to_datetime(trade['entry_time'])
                history = trades_df[
                    pd.to_datetime(trades_df['entry_time']) < entry_time
                ].copy()
                
                # Reconstruct base signal from stored data
                base_signal = {
                    'confidence': trade['ml_confidence'],
                    'signal_strength': trade.get('signal_strength', 0),
                    'indicators': {
                        'adx': trade.get('adx', 25),
                        'regime_volatile': trade.get('regime_volatile', 0),
                        'h1_trend': trade.get('h1_trend', 0),
                        'trend_confluence': trade.get('trend_confluence', 0),
                        'volume_surge': trade.get('volume_surge', 1.0),
                        'buy_sell_ratio': trade.get('buy_sell_ratio', 1.0),
                        'vwap_dist': trade.get('vwap_distance', 0),
                        'rsi': trade.get('rsi', 50),
                        'atr_pct': trade.get('atr_pct', 0)
                    }
                }
                
                features = self._build_meta_features(base_signal, history)
                X.append(list(features.values()))
                
                # Label: Was this trade profitable?
                y.append(1 if trade['outcome'] == 'WIN' else 0)
            
            X = np.array(X)
            y = np.array(y)
            
            self.feature_names = list(features.keys())
            
            # Train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, shuffle=False  # Time-series, don't shuffle
            )
            
            # Train LightGBM model
            train_data = lgb.Dataset(X_train, label=y_train)
            params = {
                'objective': 'binary',
                'metric': 'binary_logloss',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.05,
                'feature_fraction': 0.8,
                'bagging_fraction': 0.8,
                'bagging_freq': 5,
                'verbose': -1
            }
            
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                valid_sets=[lgb.Dataset(X_test, label=y_test)],
                callbacks=[lgb.early_stopping(stopping_rounds=10), lgb.log_evaluation(period=0)]
            )
            
            # Evaluate
            y_pred = self.model.predict(X_test)
            y_pred_binary = (y_pred >= 0.5).astype(int)
            
            auc = roc_auc_score(y_test, y_pred)
            accuracy = (y_pred_binary == y_test).mean()
            
            # Feature importance
            importance = self.model.feature_importance(importance_type='gain')
            feature_importance = dict(zip(self.feature_names, importance))
            top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
            
            # Save model
            model_path = self.model_dir / 'meta_learner.joblib'
            joblib.dump(self.model, model_path)
            
            # Save metadata
            meta = {
                'trained_at': datetime.now().isoformat(),
                'total_trades': len(trades_df),
                'training_samples': len(X_train),
                'test_samples': len(X_test),
                'accuracy': float(accuracy),
                'auc': float(auc),
                'features': self.feature_names,
                'top_features': [(f, float(imp)) for f, imp in top_features],
                'win_rate_in_data': float(y.mean())
            }
            
            with open(model_path.with_suffix('.meta.json'), 'w') as f:
                json.dump(meta, f, indent=2)
            
            self.training_history.append(meta)
            self.is_trained = True
            self.trades_since_retrain = 0
            
            # Log training event
            self.trade_logger.log_learning_event(
                event_type='META_RETRAIN',
                symbol=None,
                before_metric=0,
                after_metric=accuracy,
                trades_processed=len(trades_df),
                details=f"AUC: {auc:.3f}, Top feature: {top_features[0][0]}"
            )
            
            self.logger.info(f"✅ Meta-learner trained: Accuracy={accuracy:.3f}, AUC={auc:.3f}")
            self.logger.info(f"   Top features: {', '.join([f[0] for f in top_features[:5]])}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to train meta-learner: {e}", exc_info=True)
            return False
    
    def filter_signal(self, base_signal: Dict, symbol: str) -> Tuple[bool, float, str]:
        """
        Filter base model signal through meta-learner
        
        Args:
            base_signal: Signal from base model
            symbol: Trading pair
            
        Returns:
            (should_take_trade, meta_confidence, reason)
        """
        if not self.is_trained:
            # No meta-model yet, pass through with warning
            return True, base_signal.get('confidence', 0.5), "Meta-learner not trained yet"
        
        try:
            # Get recent trade history
            trade_history = self.trade_logger.get_recent_trades(limit=100, symbol=symbol)
            
            # Build meta-features
            meta_features = self._build_meta_features(base_signal, trade_history)
            
            # Prepare feature vector
            X = np.array([[meta_features[fname] for fname in self.feature_names]])
            
            # Predict
            meta_confidence = float(self.model.predict(X)[0])
            
            # Decision
            should_take = meta_confidence >= self.confidence_threshold
            
            # Reason
            if should_take:
                reason = f"Meta-learner approves ({meta_confidence*100:.1f}% confidence)"
            else:
                reason = f"Meta-learner rejects ({meta_confidence*100:.1f}% < {self.confidence_threshold*100:.0f}% threshold)"
            
            # Track decision
            self.recent_decisions.append({
                'timestamp': datetime.now(),
                'symbol': symbol,
                'base_confidence': base_signal.get('confidence'),
                'meta_confidence': meta_confidence,
                'decision': should_take,
                'reason': reason
            })
            
            # Keep only recent decisions
            if len(self.recent_decisions) > 100:
                self.recent_decisions = self.recent_decisions[-100:]
            
            return should_take, meta_confidence, reason
            
        except Exception as e:
            self.logger.error(f"Meta-learner filtering failed: {e}", exc_info=True)
            # Fall back to base signal on error
            return True, base_signal.get('confidence', 0.5), f"Meta-learner error: {str(e)}"
    
    def increment_trade_count(self):
        """Increment trade counter and trigger retraining if needed"""
        self.trades_since_retrain += 1
        
        if self.trades_since_retrain >= self.retrain_frequency:
            self.logger.info("Retraining meta-learner with new trade data...")
            self.train()
    
    def get_performance_summary(self) -> Dict:
        """Get meta-learner performance summary"""
        if not self.training_history:
            return {
                'is_trained': False,
                'total_retrains': 0
            }
        
        latest = self.training_history[-1]
        
        # Analyze recent decisions
        if self.recent_decisions:
            approved = sum(1 for d in self.recent_decisions if d['decision'])
            rejected = len(self.recent_decisions) - approved
            approval_rate = approved / len(self.recent_decisions)
        else:
            approved = 0
            rejected = 0
            approval_rate = 0
        
        return {
            'is_trained': self.is_trained,
            'total_retrains': len(self.training_history),
            'last_trained': latest['trained_at'],
            'accuracy': latest['accuracy'],
            'auc': latest['auc'],
            'trades_since_retrain': self.trades_since_retrain,
            'recent_decisions': len(self.recent_decisions),
            'signals_approved': approved,
            'signals_rejected': rejected,
            'approval_rate': approval_rate,
            'top_features': latest.get('top_features', [])[:5]
        }
