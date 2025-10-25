"""
Model Decay Detection and Monitoring
Tracks model performance and triggers retraining when degradation detected
"""
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from collections import deque


logger = logging.getLogger(__name__)


class ModelMonitor:
    """Monitor ML model performance and detect decay."""
    
    def __init__(self, window_size: int = 100, decay_threshold: float = 0.10):
        """
        Args:
            window_size: Number of recent predictions to track
            decay_threshold: Performance drop threshold to trigger retraining (e.g., 0.10 = 10%)
        """
        self.window_size = window_size
        self.decay_threshold = decay_threshold
        self.logger = logging.getLogger(__name__)
        
        # Track predictions and outcomes per symbol
        self.symbol_predictions = {}  # symbol -> deque of (prediction, actual, confidence)
        self.symbol_metrics = {}      # symbol -> latest metrics
        self.last_retrain_time = {}   # symbol -> timestamp
        
        # Store to disk
        self.state_file = Path('data/model_monitor_state.json')
        self._load_state()
    
    def _load_state(self):
        """Load monitoring state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.last_retrain_time = state.get('last_retrain_time', {})
                    self.logger.info(f"Loaded model monitor state for {len(self.last_retrain_time)} symbols")
            except Exception as e:
                self.logger.error(f"Failed to load monitor state: {e}")
    
    def _save_state(self):
        """Save monitoring state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'last_retrain_time': self.last_retrain_time,
                'updated_at': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save monitor state: {e}")
    
    def record_prediction(self, symbol: str, predicted: int, confidence: float, actual: Optional[int] = None):
        """
        Record a model prediction and optionally the actual outcome.
        
        Args:
            symbol: Trading pair
            predicted: Model prediction (0 or 1)
            confidence: Prediction confidence (0-1)
            actual: Actual outcome (0 or 1) if known
        """
        if symbol not in self.symbol_predictions:
            self.symbol_predictions[symbol] = deque(maxlen=self.window_size)
        
        self.symbol_predictions[symbol].append({
            'predicted': predicted,
            'confidence': confidence,
            'actual': actual,
            'timestamp': datetime.now().isoformat()
        })
    
    def update_actual_outcome(self, symbol: str, actual: int):
        """
        Update the most recent prediction with actual outcome.
        
        Args:
            symbol: Trading pair
            actual: Actual outcome (1 = profitable, 0 = unprofitable)
        """
        if symbol in self.symbol_predictions and self.symbol_predictions[symbol]:
            # Update most recent prediction
            self.symbol_predictions[symbol][-1]['actual'] = actual
            
            # Recalculate metrics
            self._calculate_metrics(symbol)
    
    def _calculate_metrics(self, symbol: str) -> Dict:
        """Calculate performance metrics for a symbol."""
        if symbol not in self.symbol_predictions or not self.symbol_predictions[symbol]:
            return {}
        
        predictions = list(self.symbol_predictions[symbol])
        
        # Filter to only predictions with known outcomes
        complete = [p for p in predictions if p['actual'] is not None]
        
        if len(complete) < 10:  # Need minimum sample
            return {}
        
        # Calculate metrics
        y_pred = [p['predicted'] for p in complete]
        y_true = [p['actual'] for p in complete]
        confidences = [p['confidence'] for p in complete]
        
        # Accuracy
        correct = sum(1 for p, t in zip(y_pred, y_true) if p == t)
        accuracy = correct / len(complete)
        
        # Hit rate (for BUY signals specifically)
        buy_signals = [(p, t) for p, t in zip(y_pred, y_true) if p == 1]
        hit_rate = sum(1 for p, t in buy_signals if t == 1) / len(buy_signals) if buy_signals else 0
        
        # Calibration (confidence vs actual accuracy)
        high_conf = [(p, t) for p, t, c in zip(y_pred, y_true, confidences) if c > 0.7]
        high_conf_accuracy = sum(1 for p, t in high_conf if p == t) / len(high_conf) if high_conf else 0
        
        # Recent trend (last 20 vs previous)
        if len(complete) >= 40:
            recent_20 = complete[-20:]
            previous_20 = complete[-40:-20]
            
            recent_acc = sum(1 for p in recent_20 if p['predicted'] == p['actual']) / 20
            previous_acc = sum(1 for p in previous_20 if p['predicted'] == p['actual']) / 20
            
            drift = recent_acc - previous_acc
        else:
            drift = 0
        
        metrics = {
            'symbol': symbol,
            'accuracy': accuracy,
            'hit_rate': hit_rate,
            'high_conf_accuracy': high_conf_accuracy,
            'drift': drift,
            'sample_size': len(complete),
            'updated_at': datetime.now().isoformat()
        }
        
        self.symbol_metrics[symbol] = metrics
        return metrics
    
    def check_decay(self, symbol: str) -> Dict:
        """
        Check if model has decayed and needs retraining.
        
        Returns:
            dict with 'needs_retrain' (bool), 'reason' (str), 'metrics' (dict)
        """
        if symbol not in self.symbol_predictions:
            return {'needs_retrain': False, 'reason': 'No data', 'metrics': {}}
        
        # Calculate current metrics
        metrics = self._calculate_metrics(symbol)
        
        if not metrics or metrics.get('sample_size', 0) < 20:
            return {
                'needs_retrain': False,
                'reason': f"Insufficient data (need 20, have {metrics.get('sample_size', 0)})",
                'metrics': metrics
            }
        
        # Check for decay conditions
        reasons = []
        
        # 1. Accuracy below threshold
        min_accuracy = 0.55
        if metrics['accuracy'] < min_accuracy:
            reasons.append(f"Accuracy {metrics['accuracy']:.2%} < {min_accuracy:.0%}")
        
        # 2. Hit rate too low
        min_hit_rate = 0.50
        if metrics['hit_rate'] < min_hit_rate:
            reasons.append(f"Hit rate {metrics['hit_rate']:.2%} < {min_hit_rate:.0%}")
        
        # 3. Calibration drift (high confidence predictions not accurate)
        if metrics['high_conf_accuracy'] < metrics['accuracy'] - 0.10:
            reasons.append(f"Calibration drift (high-conf acc {metrics['high_conf_accuracy']:.2%})")
        
        # 4. Negative drift
        if metrics['drift'] < -self.decay_threshold:
            reasons.append(f"Performance declining (drift: {metrics['drift']:.2%})")
        
        # Check cooldown period (don't retrain too frequently)
        if symbol in self.last_retrain_time:
            last_retrain = datetime.fromisoformat(self.last_retrain_time[symbol])
            cooldown_days = 3  # Minimum 3 days between retrains
            if datetime.now() - last_retrain < timedelta(days=cooldown_days):
                return {
                    'needs_retrain': False,
                    'reason': f"Cooldown period ({cooldown_days} days)",
                    'metrics': metrics
                }
        
        needs_retrain = len(reasons) > 0
        
        if needs_retrain:
            self.logger.warning(f"🚨 Model decay detected for {symbol}: {', '.join(reasons)}")
        
        return {
            'needs_retrain': needs_retrain,
            'reason': '; '.join(reasons) if reasons else 'Performance acceptable',
            'metrics': metrics
        }
    
    def record_retrain(self, symbol: str):
        """Record that a model was retrained."""
        self.last_retrain_time[symbol] = datetime.now().isoformat()
        self._save_state()
        self.logger.info(f"✅ Recorded retrain for {symbol}")
        
        # Reset tracking window for fresh start
        if symbol in self.symbol_predictions:
            self.symbol_predictions[symbol].clear()
    
    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get current metrics for all symbols."""
        return {symbol: self._calculate_metrics(symbol) 
                for symbol in self.symbol_predictions.keys()}
    
    def generate_report(self) -> str:
        """Generate a text report of all models' health."""
        all_metrics = self.get_all_metrics()
        
        if not all_metrics:
            return "No model data available yet."
        
        lines = ["📊 Model Health Report", "=" * 60]
        
        for symbol, metrics in sorted(all_metrics.items()):
            if not metrics:
                continue
            
            status = "✅" if metrics['accuracy'] >= 0.55 and metrics['hit_rate'] >= 0.50 else "⚠️"
            
            lines.append(f"\n{status} {symbol}")
            lines.append(f"   Accuracy: {metrics['accuracy']:.2%} | Hit Rate: {metrics['hit_rate']:.2%}")
            lines.append(f"   High-Conf Acc: {metrics['high_conf_accuracy']:.2%} | Drift: {metrics['drift']:+.2%}")
            lines.append(f"   Sample: {metrics['sample_size']} trades")
            
            # Check if needs retrain
            decay_check = self.check_decay(symbol)
            if decay_check['needs_retrain']:
                lines.append(f"   🚨 NEEDS RETRAIN: {decay_check['reason']}")
        
        return '\n'.join(lines)
