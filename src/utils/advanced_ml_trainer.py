"""
Advanced ML Model Trainer
- XGBoost and LightGBM models
- Optuna hyperparameter optimization
- Feature selection
- Ensemble stacking
"""
import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.feature_selection import SelectFromModel
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False


logger = logging.getLogger(__name__)


class AdvancedMLTrainer:
    """
    Advanced ML training pipeline with state-of-the-art models
    """
    
    def __init__(self, 
                 model_dir: str,
                 symbol: str,
                 interval: str,
                 optimize_hyperparams: bool = True,
                 n_trials: int = 50):
        """
        Args:
            model_dir: Directory to save models
            symbol: Trading symbol
            interval: Timeframe
            optimize_hyperparams: Whether to use Optuna for hyperparameter tuning
            n_trials: Number of Optuna trials
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.symbol = symbol
        self.interval = interval
        self.optimize_hyperparams = optimize_hyperparams and HAS_OPTUNA
        self.n_trials = n_trials
        
        # Model paths
        self.model_path = self.model_dir / f"{symbol}_{interval}_advanced_ml.joblib"
        self.meta_path = self.model_dir / f"{symbol}_{interval}_advanced_ml.meta.json"
        self.scaler_path = self.model_dir / f"{symbol}_{interval}_scaler.joblib"
        
        # Feature selection
        self.feature_selector = None
        self.scaler = StandardScaler()
        self.selected_features = None
    
    def _calculate_metrics(self, y_true, y_pred, y_proba=None) -> Dict[str, float]:
        """Calculate comprehensive metrics"""
        metrics = {
            'accuracy': float(accuracy_score(y_true, y_pred)),
            'precision': float(precision_score(y_true, y_pred, zero_division=0)),
            'recall': float(recall_score(y_true, y_pred, zero_division=0)),
            'f1': float(f1_score(y_true, y_pred, zero_division=0))
        }
        
        # Add AUC if probabilities available
        if y_proba is not None:
            try:
                metrics['auc'] = float(roc_auc_score(y_true, y_proba))
            except:
                metrics['auc'] = 0.5
        
        return metrics
    
    def _select_features(self, X: pd.DataFrame, y: pd.Series, threshold: str = "median") -> pd.DataFrame:
        """
        Select most important features using tree-based model
        
        Args:
            X: Feature matrix
            y: Target vector
            threshold: Feature importance threshold
            
        Returns:
            DataFrame with selected features
        """
        logger.info("Performing feature selection...")
        
        # Train a simple model for feature selection
        if HAS_XGB:
            selector_model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                random_state=42,
                n_jobs=-1
            )
        else:
            selector_model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                random_state=42
            )
        
        selector_model.fit(X, y)
        
        # Get feature importances
        importances = pd.Series(
            selector_model.feature_importances_,
            index=X.columns
        ).sort_values(ascending=False)
        
        logger.info(f"Top 10 features: {importances.head(10).to_dict()}")
        
        # Select features
        self.feature_selector = SelectFromModel(selector_model, threshold=threshold, prefit=True)
        X_selected = self.feature_selector.transform(X)
        
        # Get selected feature names
        selected_mask = self.feature_selector.get_support()
        self.selected_features = X.columns[selected_mask].tolist()
        
        logger.info(f"Selected {len(self.selected_features)}/{len(X.columns)} features")
        
        return pd.DataFrame(X_selected, columns=self.selected_features, index=X.index)
    
    def _create_xgboost_model(self, params: Dict = None) -> Any:
        """Create XGBoost model"""
        if not HAS_XGB:
            return None
        
        default_params = {
            'n_estimators': 300,
            'max_depth': 7,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'gamma': 0.1,
            'min_child_weight': 3,
            'random_state': 42,
            'n_jobs': -1,
            'tree_method': 'hist'
        }
        
        if params:
            default_params.update(params)
        
        return xgb.XGBClassifier(**default_params)
    
    def _create_lightgbm_model(self, params: Dict = None) -> Any:
        """Create LightGBM model"""
        if not HAS_LGB:
            return None
        
        default_params = {
            'n_estimators': 300,
            'max_depth': 7,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_samples': 20,
            'random_state': 42,
            'n_jobs': -1,
            'verbose': -1
        }
        
        if params:
            default_params.update(params)
        
        return lgb.LGBMClassifier(**default_params)
    
    def _optimize_xgboost(self, X_train, y_train, X_val, y_val) -> Dict:
        """Optimize XGBoost hyperparameters with Optuna"""
        
        def objective(trial):
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'gamma': trial.suggest_float('gamma', 0, 0.5),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
            }
            
            model = self._create_xgboost_model(params)
            model.fit(X_train, y_train)
            
            y_pred = model.predict(X_val)
            f1 = f1_score(y_val, y_pred)
            
            return f1
        
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)
        
        logger.info(f"XGBoost best F1: {study.best_value:.4f}")
        logger.info(f"Best params: {study.best_params}")
        
        return study.best_params
    
    def _optimize_lightgbm(self, X_train, y_train, X_val, y_val) -> Dict:
        """Optimize LightGBM hyperparameters with Optuna"""
        
        def objective(trial):
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
                'reg_alpha': trial.suggest_float('reg_alpha', 0, 1.0),
                'reg_lambda': trial.suggest_float('reg_lambda', 0, 1.0),
            }
            
            model = self._create_lightgbm_model(params)
            model.fit(X_train, y_train)
            
            y_pred = model.predict(X_val)
            f1 = f1_score(y_val, y_pred)
            
            return f1
        
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)
        
        logger.info(f"LightGBM best F1: {study.best_value:.4f}")
        logger.info(f"Best params: {study.best_params}")
        
        return study.best_params
    
    def train_models(self, X: pd.DataFrame, y: pd.Series) -> Tuple[Any, Dict]:
        """
        Train multiple models and select the best one
        
        Args:
            X: Feature matrix
            y: Target vector
            
        Returns:
            Tuple of (best_model, metadata)
        """
        logger.info(f"Training models on {len(X)} samples with {len(X.columns)} features")
        
        # Feature selection
        if len(X.columns) > 20:
            X = self._select_features(X, y, threshold="median")
        else:
            self.selected_features = list(X.columns)
        
        # Normalize features
        X_scaled = pd.DataFrame(
            self.scaler.fit_transform(X),
            columns=X.columns,
            index=X.index
        )
        
        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        
        models_to_test = []
        
        # XGBoost
        if HAS_XGB:
            if self.optimize_hyperparams:
                logger.info("Optimizing XGBoost hyperparameters...")
                # Use first split for optimization
                train_idx, val_idx = list(tscv.split(X_scaled))[0]
                X_train, X_val = X_scaled.iloc[train_idx], X_scaled.iloc[val_idx]
                y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
                
                best_params = self._optimize_xgboost(X_train, y_train, X_val, y_val)
                xgb_model = self._create_xgboost_model(best_params)
            else:
                xgb_model = self._create_xgboost_model()
            
            models_to_test.append(('XGBoost', xgb_model))
        
        # LightGBM
        if HAS_LGB:
            if self.optimize_hyperparams:
                logger.info("Optimizing LightGBM hyperparameters...")
                train_idx, val_idx = list(tscv.split(X_scaled))[0]
                X_train, X_val = X_scaled.iloc[train_idx], X_scaled.iloc[val_idx]
                y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
                
                best_params = self._optimize_lightgbm(X_train, y_train, X_val, y_val)
                lgb_model = self._create_lightgbm_model(best_params)
            else:
                lgb_model = self._create_lightgbm_model()
            
            models_to_test.append(('LightGBM', lgb_model))
        
        # Fallback: GradientBoosting
        models_to_test.append((
            'GradientBoosting',
            GradientBoostingClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                random_state=42
            )
        ))
        
        # Evaluate each model
        best_model = None
        best_metrics = None
        best_score = -1
        
        for model_name, model in models_to_test:
            logger.info(f"Evaluating {model_name}...")
            cv_metrics = []
            
            for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X_scaled)):
                X_train, X_val = X_scaled.iloc[train_idx], X_scaled.iloc[val_idx]
                y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
                
                model.fit(X_train, y_train)
                
                y_pred = model.predict(X_val)
                y_proba = model.predict_proba(X_val)[:, 1] if hasattr(model, 'predict_proba') else None
                
                metrics = self._calculate_metrics(y_val, y_pred, y_proba)
                cv_metrics.append(metrics)
            
            # Average metrics
            avg_metrics = {k: np.mean([m[k] for m in cv_metrics]) for k in cv_metrics[0].keys()}
            
            logger.info(f"  {model_name} - F1: {avg_metrics['f1']:.4f}, "
                       f"Precision: {avg_metrics['precision']:.4f}, "
                       f"Recall: {avg_metrics['recall']:.4f}")
            
            if 'auc' in avg_metrics:
                logger.info(f"  {model_name} - AUC: {avg_metrics['auc']:.4f}")
            
            # Select best model by F1 score
            if avg_metrics['f1'] > best_score:
                best_score = avg_metrics['f1']
                best_model = model
                best_metrics = {**avg_metrics, 'model_name': model_name}
        
        # Retrain best model on full dataset
        logger.info(f"Retraining best model ({best_metrics['model_name']}) on full dataset...")
        best_model.fit(X_scaled, y)
        
        # Metadata
        metadata = {
            **best_metrics,
            'samples': len(X),
            'features': self.selected_features,
            'n_features': len(self.selected_features),
            'trained_at': int(time.time()),
            'symbol': self.symbol,
            'interval': self.interval
        }
        
        return best_model, metadata
    
    def save_model(self, model: Any, metadata: Dict):
        """Save model and metadata to disk"""
        # Save model
        joblib.dump(model, self.model_path)
        logger.info(f"Model saved to {self.model_path}")
        
        # Save scaler
        joblib.dump(self.scaler, self.scaler_path)
        
        # Save metadata
        with open(self.meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Metadata saved to {self.meta_path}")
    
    def load_model(self) -> Tuple[Optional[Any], Optional[Dict]]:
        """Load model and metadata from disk"""
        if not self.model_path.exists():
            return None, None
        
        model = joblib.load(self.model_path)
        
        if self.scaler_path.exists():
            self.scaler = joblib.load(self.scaler_path)
        
        metadata = None
        if self.meta_path.exists():
            with open(self.meta_path, 'r') as f:
                metadata = json.load(f)
                self.selected_features = metadata.get('features', [])
        
        return model, metadata
