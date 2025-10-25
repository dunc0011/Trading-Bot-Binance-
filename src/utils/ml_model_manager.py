"""
ML Model Manager for trading strategy
Handles feature engineering, training, prediction, and model persistence
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score


@dataclass
class ModelSpec:
    """Model specification with hyperparameters"""
    name: str
    params: Dict[str, Any]


class MLModelManager:
    """Manages ML model training, persistence, and predictions for trading"""
    
    def __init__(self, config, model_dir: str, symbol: str, interval: str, logger: Optional[logging.Logger] = None):
        self.config = config
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.symbol = symbol
        self.interval = interval
        self.logger = logger or logging.getLogger(__name__)
        
        # Model paths
        self.model_path = self.model_dir / f"{symbol}_{interval}_ml_ema.joblib"
        self.meta_path = self.model_dir / f"{symbol}_{interval}_ml_ema.meta.json"
        
        # Model state
        self._model = None
        self._model_mtime = None  # Track model file modification time for hot-reload
        self._threshold = float(getattr(config, "ml_proba_threshold", 0.55))
    
    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def build_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[pd.Series]]:
        """
        Build features from OHLCV data with proper lag to prevent data leakage
        
        Args:
            df: DataFrame with columns: timestamp, open, high, low, close, volume
        
        Returns:
            Tuple of (features DataFrame, target Series or None)
        """
        if len(df) < 50:
            self.logger.warning(f"Insufficient data for feature engineering: {len(df)} rows")
            return pd.DataFrame(), None
        
        # Ensure numeric types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate indicators (no lookahead bias)
        ema5 = df['close'].ewm(span=5, adjust=False).mean()
        ema8 = df['close'].ewm(span=8, adjust=False).mean()
        rsi = self._rsi(df['close'], period=14)
        
        # ATR calculation
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift(1))
        low_close = abs(df['low'] - df['close'].shift(1))
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        
        # Build feature matrix
        features = pd.DataFrame({
            'ema5': ema5,
            'ema8': ema8,
            'ema_cross': (ema5 - ema8) / df['close'],  # Normalized
            'ema_cross_momentum': (ema5 - ema8).diff(),  # Rate of change
            'rsi': rsi,
            'atr': atr,
            'atr_pct': atr / df['close'],  # Normalized ATR
            'ret_1': df['close'].pct_change(1),
            'ret_5': df['close'].pct_change(5),
            'vol': df['volume'].astype(float),
            'vol_sma': df['volume'].astype(float).rolling(20).mean(),
        }, index=df.index)
        
        # Lag ALL features by 1 to prevent leakage
        # We predict return at time t using features known at time t-1
        features = features.shift(1)
        
        # Target: binary signal for profitable trade
        # Using forward return, but this is the label not a feature
        horizon = int(getattr(self.config, "ml_target_horizon", 1))
        threshold = float(getattr(self.config, "ml_target_return_threshold", 0.001))
        
        future_return = df['close'].pct_change(horizon)
        target = (future_return > threshold).astype(int)
        
        # Combine and drop NaN rows
        result = pd.concat([features, target.rename('target')], axis=1).dropna()
        
        if len(result) == 0:
            self.logger.warning("All rows dropped after feature engineering")
            return pd.DataFrame(), None
        
        X = result.drop(columns=['target'])
        y = result['target']
        
        self.logger.debug(f"Built features: {len(X)} samples, {len(X.columns)} features")
        return X, y
    
    def _create_model(self, spec: ModelSpec):
        """Create sklearn model from specification"""
        if spec.name == "RandomForest":
            return RandomForestClassifier(**spec.params)
        elif spec.name == "GradientBoosting":
            return GradientBoostingClassifier(**spec.params)
        elif spec.name == "LogisticRegression":
            return LogisticRegression(**spec.params)
        else:
            raise ValueError(f"Unknown model type: {spec.name}")
    
    def _calculate_metrics(self, y_true, y_pred) -> Dict[str, float]:
        """Calculate classification metrics"""
        return {
            'accuracy': float(accuracy_score(y_true, y_pred)),
            'precision': float(precision_score(y_true, y_pred, zero_division=0)),
            'recall': float(recall_score(y_true, y_pred, zero_division=0)),
            'f1': float(f1_score(y_true, y_pred, zero_division=0))
        }
    
    def _aggregate_metrics(self, metrics_list) -> Dict[str, float]:
        """Aggregate metrics across folds"""
        if not metrics_list:
            return {'accuracy': 0.0, 'precision': 0.0, 'recall': 0.0, 'f1': 0.0}
        
        return {
            key: float(np.mean([m[key] for m in metrics_list]))
            for key in metrics_list[0].keys()
        }
    
    def ensure_loaded(self, force_reload: bool = False):
        """Load model from disk with hot-reload support
        
        Args:
            force_reload: Force reload even if model is already loaded
        """
        if not self.model_path.exists():
            return
        
        try:
            # Get current model file modification time
            current_mtime = os.path.getmtime(self.model_path)
            
            # Check if we need to reload
            should_reload = (
                force_reload or 
                self._model is None or 
                self._model_mtime is None or 
                current_mtime > self._model_mtime
            )
            
            if should_reload:
                self._model = joblib.load(self.model_path)
                self._model_mtime = current_mtime
                
                # Load metadata if available
                meta = {}
                if self.meta_path.exists():
                    with open(self.meta_path, 'r') as f:
                        meta = json.load(f)
                
                reload_msg = "🔄 Reloaded" if self._model is not None and not force_reload else "Loaded"
                self.logger.info(
                    f"{reload_msg} ML model from {self.model_path.name} | "
                    f"trained: {meta.get('trained_at', 'unknown')} | "
                    f"f1={meta.get('f1', 0):.3f}"
                )
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}", exc_info=True)
            self._model = None
            self._model_mtime = None
    
    def train_and_persist(self, candles: pd.DataFrame) -> Dict[str, Any]:
        """
        Train multiple models using walk-forward validation and persist the best
        
        Args:
            candles: DataFrame with OHLCV data
        
        Returns:
            Dictionary with training metadata and metrics
        """
        self.logger.info(f"Training ML model on {len(candles)} candles")
        
        # Build features
        X, y = self.build_features(candles)
        
        if X.empty or y is None:
            raise ValueError("Feature engineering produced no valid samples")
        
        # Define candidate models
        models = [
            ModelSpec("RandomForest", {
                "n_estimators": 200,
                "max_depth": 10,
                "min_samples_split": 50,
                "random_state": 42,
                "n_jobs": -1
            }),
            ModelSpec("GradientBoosting", {
                "n_estimators": 100,
                "max_depth": 5,
                "learning_rate": 0.1,
                "random_state": 42
            }),
            ModelSpec("LogisticRegression", {
                "max_iter": 2000,
                "n_jobs": -1,
                "random_state": 42
            })
        ]
        
        # Walk-forward validation
        n_splits = int(getattr(self.config, "ml_wfv_splits", 5))
        tscv = TimeSeriesSplit(n_splits=n_splits)
        
        best_model = None
        best_meta = None
        best_score = -1
        
        for spec in models:
            self.logger.info(f"Evaluating {spec.name}...")
            
            try:
                model = self._create_model(spec)
                cv_metrics = []
                
                # Cross-validation
                for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
                    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
                    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
                    
                    # Train
                    model.fit(X_train, y_train)
                    
                    # Predict with threshold
                    if hasattr(model, 'predict_proba'):
                        proba = model.predict_proba(X_test)[:, 1]
                        y_pred = (proba >= self._threshold).astype(int)
                    else:
                        y_pred = model.predict(X_test)
                    
                    # Metrics
                    fold_metrics = self._calculate_metrics(y_test, y_pred)
                    cv_metrics.append(fold_metrics)
                    
                    self.logger.debug(f"  Fold {fold_idx+1}: f1={fold_metrics['f1']:.3f}")
                
                # Aggregate
                agg_metrics = self._aggregate_metrics(cv_metrics)
                self.logger.info(f"  {spec.name} - Avg F1: {agg_metrics['f1']:.3f}, "
                               f"Precision: {agg_metrics['precision']:.3f}, "
                               f"Recall: {agg_metrics['recall']:.3f}")
                
                # Track best
                if agg_metrics['f1'] > best_score:
                    best_score = agg_metrics['f1']
                    best_meta = {**agg_metrics, 'model': spec.name, 'params': spec.params}
                    
                    # Refit on full dataset
                    best_model = self._create_model(spec)
                    best_model.fit(X, y)
            
            except Exception as e:
                self.logger.error(f"Error training {spec.name}: {e}", exc_info=True)
                continue
        
        if best_model is None:
            raise RuntimeError("No models successfully trained")
        
        # Persist model atomically
        tmp_path = self.model_path.with_suffix('.tmp')
        joblib.dump(best_model, tmp_path)
        os.replace(tmp_path, self.model_path)
        
        # Save metadata
        meta = {
            **best_meta,
            'trained_at': int(time.time()),
            'samples': len(X),
            'features': list(X.columns),
            'symbol': self.symbol,
            'interval': self.interval,
            'threshold': self._threshold
        }
        
        with open(self.meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        
        self._model = best_model
        self.logger.info(f"✅ Trained and persisted {meta['model']} with F1={meta['f1']:.3f}")
        
        return meta
    
    def predict_signal(self, features: pd.DataFrame) -> int:
        """
        Predict trading signal from features
        
        Args:
            features: Single-row DataFrame with feature values
        
        Returns:
            1 for BUY signal, 0 for HOLD
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call ensure_loaded() first.")
        
        if len(features) != 1:
            raise ValueError(f"Expected 1 row, got {len(features)}")
        
        try:
            if hasattr(self._model, 'predict_proba'):
                proba = self._model.predict_proba(features)[0, 1]
                self.logger.debug(f"Prediction probability: {proba:.3f}")
                return 1 if proba >= self._threshold else 0
            else:
                pred = self._model.predict(features)[0]
                return int(pred == 1)
        
        except Exception as e:
            self.logger.error(f"Prediction error: {e}", exc_info=True)
            return 0  # Default to HOLD on error
