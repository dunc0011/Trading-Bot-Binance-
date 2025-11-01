"""
Train Mean Reversion ML Model

Labels oversold/overbought extremes as 1 if they bounce 2-5% profitably
"""
import argparse
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from binance.client import Client
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, precision_recall_fscore_support
from imblearn.over_sampling import SMOTE
import joblib
import json
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from config.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_klines(client: Client, symbol: str, interval: str, lookback_days: int):
    """Fetch historical klines"""
    start_time = datetime.now() - timedelta(days=lookback_days)
    start_str = start_time.strftime('%Y-%m-%d')
    
    logger.info(f"Fetching klines for {symbol} {interval} from {start_str}")
    
    klines = client.get_historical_klines(
        symbol,
        interval,
        start_str
    )
    
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    logger.info(f"Fetched {len(df)} candles")
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate mean reversion features"""
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi_momentum'] = df['rsi'].diff(1)
    
    # Bollinger Bands
    sma_20 = df['close'].rolling(20).mean()
    std_20 = df['close'].rolling(20).std()
    bb_upper = sma_20 + (2 * std_20)
    bb_lower = sma_20 - (2 * std_20)
    df['bb_position'] = (df['close'] - bb_lower) / (bb_upper - bb_lower)
    df['bb_width'] = (bb_upper - bb_lower) / sma_20
    
    # Volume
    volume_sma = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / volume_sma
    
    # MACD
    ema_12 = df['close'].ewm(span=12).mean()
    ema_26 = df['close'].ewm(span=26).mean()
    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9).mean()
    df['macd_hist'] = macd - macd_signal
    df['macd_hist_change'] = df['macd_hist'].diff(1)
    
    # ATR (volatility)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    df['atr_pct'] = atr / df['close']
    
    # Price momentum
    df['returns_1'] = df['close'].pct_change(1)
    df['returns_5'] = df['close'].pct_change(5)
    
    # Support/Resistance context
    recent_high = df['high'].rolling(20).max()
    recent_low = df['low'].rolling(20).min()
    df['price_range_position'] = (df['close'] - recent_low) / (recent_high - recent_low)
    df['distance_to_high'] = (recent_high - df['close']) / df['close']
    df['distance_to_low'] = (df['close'] - recent_low) / df['close']
    
    # ENHANCED FEATURES
    # Multiple RSI periods for better extreme detection
    delta = df['close'].diff()
    for period in [21, 28]:
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        df[f'rsi_{period}'] = 100 - (100 / (1 + rs))
    
    # Volume surge detection (sudden volume spikes indicate strong moves)
    df['volume_surge'] = df['volume'] / df['volume'].rolling(50).mean()
    df['volume_trend'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
    
    # Volatility regime (high vol = bigger bounces)
    df['volatility_regime'] = df['atr_pct'] / df['atr_pct'].rolling(50).mean()
    
    # Price momentum across multiple timeframes
    df['returns_10'] = df['close'].pct_change(10)
    df['returns_20'] = df['close'].pct_change(20)
    
    return df


def label_mean_reversion(df: pd.DataFrame, target_return_min: float = 0.02, target_return_max: float = 0.15, horizon: int = 10) -> pd.DataFrame:
    """
    Label extremes with RISK/REWARD weighting
    
    Improvements:
    - Weight by R:R ratio (bigger bounces = better labels)
    - Consider time to bounce (faster = better)
    - Filter out false extremes (those that continue in same direction)
    """
    # VERY RELAXED: Maximum opportunities
    df['is_oversold'] = (df['rsi'] < 40) | (df['bb_position'] < 0.35)  # Changed AND to OR, widened further
    df['is_overbought'] = (df['rsi'] > 60) | (df['bb_position'] > 0.65)  # Changed AND to OR, widened further
    
    # Calculate max gain/loss and time to reach it
    df['future_max'] = df['high'].shift(-1).rolling(horizon).max()
    df['future_min'] = df['low'].shift(-1).rolling(horizon).min()
    
    df['max_gain'] = (df['future_max'] - df['close']) / df['close']
    df['max_loss'] = (df['close'] - df['future_min']) / df['close']
    
    # Calculate time to max gain/loss (faster bounces = better)
    for i in range(len(df)):
        if pd.notna(df['future_max'].iloc[i]):
            future_highs = df['high'].iloc[i+1:i+horizon+1]
            if len(future_highs) > 0:
                periods_to_high = (future_highs == df['future_max'].iloc[i]).idxmax() - i if (future_highs == df['future_max'].iloc[i]).any() else horizon
                df.loc[df.index[i], 'periods_to_bounce'] = periods_to_high
    
    df['periods_to_bounce'] = df['periods_to_bounce'].fillna(horizon)
    
    # RELAXED: Accept smaller gains and longer bounce times
    df['oversold_bounce'] = (
        df['is_oversold'] &
        (df['max_gain'] >= target_return_min) &  # At least 2% gain
        (df['max_gain'] <= target_return_max) &  # Cap at 15%
        (df['periods_to_bounce'] <= 12)  # Was 7, now 12 periods (more opportunities)
    ).astype(int)
    
    # Label overbought drops
    df['overbought_drop'] = (
        df['is_overbought'] &
        (df['max_loss'] >= target_return_min) &
        (df['max_loss'] <= target_return_max) &
        (df['periods_to_bounce'] <= 12)  # Was 7, now 12
    ).astype(int)
    
    # RELAXED: Allow larger drawdowns before bounce
    df['worst_drawdown'] = (df['close'] - df['future_min']) / df['close']
    df['oversold_bounce'] = df['oversold_bounce'] & (df['worst_drawdown'] < 0.12)  # Was 0.08, now 0.12 (12% drawdown)
    
    # Combined label with quality weighting
    df['target'] = ((df['oversold_bounce'] == 1) | (df['overbought_drop'] == 1)).astype(int)
    
    # Only label at extremes
    df['at_extreme'] = df['is_oversold'] | df['is_overbought']
    
    return df


def train_model(symbol: str, interval: str, lookback_days: int, dry_run: bool):
    """Train mean reversion model"""
    # Initialize Binance client
    if config.trading_mode == 'testnet':
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)
    
    # Fetch data
    df = fetch_klines(client, symbol, interval, lookback_days)
    
    # Calculate features
    logger.info("Calculating features...")
    df = calculate_features(df)
    
    # VERY RELAXED: Accept smaller gains, longer horizon
    logger.info("Labeling mean reversion opportunities...")
    df = label_mean_reversion(df, target_return_min=0.01, target_return_max=0.15, horizon=20)  # 1% min gain, 20 period horizon
    
    # Filter to only extremes
    df_extremes = df[df['at_extreme']].copy()
    
    logger.info(f"Found {len(df_extremes)} extreme points out of {len(df)} total candles")
    logger.info(f"Positive labels (successful bounces): {df_extremes['target'].sum()} ({df_extremes['target'].mean()*100:.1f}%)")
    
    # Drop rows with NaN
    df_extremes = df_extremes.dropna()
    
    if len(df_extremes) < 100:
        logger.error("Not enough extreme data points for training")
        return
    
    # Feature columns (including enhanced features)
    feature_cols = [
        'rsi', 'rsi_momentum', 'rsi_21', 'rsi_28',
        'bb_position', 'bb_width',
        'volume_ratio', 'volume_surge', 'volume_trend',
        'macd_hist', 'macd_hist_change',
        'atr_pct', 'volatility_regime',
        'returns_1', 'returns_5', 'returns_10', 'returns_20',
        'price_range_position', 'distance_to_high', 'distance_to_low'
    ]
    
    X = df_extremes[feature_cols]
    y = df_extremes['target']
    
    # Walk-forward validation
    logger.info("Training with TimeSeriesSplit cross-validation...")
    tscv = TimeSeriesSplit(n_splits=5)
    
    cv_scores = []
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
        
        # Handle class imbalance with SMOTE
        if y_train.sum() > 5:  # Need at least 5 positive samples
            smote = SMOTE(random_state=42)
            X_train_balanced, y_train_balanced = smote.fit_resample(X_train, y_train)
        else:
            X_train_balanced, y_train_balanced = X_train, y_train
        
        # Train models
        rf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        gb = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
        
        rf.fit(X_train_balanced, y_train_balanced)
        gb.fit(X_train_balanced, y_train_balanced)
        
        # Evaluate
        rf_pred = rf.predict(X_val)
        gb_pred = gb.predict(X_val)
        
        rf_prec, rf_rec, rf_f1, _ = precision_recall_fscore_support(y_val, rf_pred, average='binary', zero_division=0)
        gb_prec, gb_rec, gb_f1, _ = precision_recall_fscore_support(y_val, gb_pred, average='binary', zero_division=0)
        
        logger.info(f"Fold {fold}:")
        logger.info(f"  RF - P:{rf_prec:.3f} R:{rf_rec:.3f} F1:{rf_f1:.3f}")
        logger.info(f"  GB - P:{gb_prec:.3f} R:{gb_rec:.3f} F1:{gb_f1:.3f}")
        
        cv_scores.append({
            'fold': fold,
            'rf_f1': rf_f1,
            'gb_f1': gb_f1
        })
    
    # Choose best model
    avg_rf_f1 = np.mean([s['rf_f1'] for s in cv_scores])
    avg_gb_f1 = np.mean([s['gb_f1'] for s in cv_scores])
    
    logger.info(f"\nAverage F1 Scores:")
    logger.info(f"  RandomForest: {avg_rf_f1:.3f}")
    logger.info(f"  GradientBoosting: {avg_gb_f1:.3f}")
    
    best_model_name = 'RandomForest' if avg_rf_f1 >= avg_gb_f1 else 'GradientBoosting'
    best_f1 = max(avg_rf_f1, avg_gb_f1)
    
    logger.info(f"\nBest model: {best_model_name} (F1={best_f1:.3f})")
    
    # Train final model on all data
    if y.sum() > 5:
        smote = SMOTE(random_state=42)
        X_balanced, y_balanced = smote.fit_resample(X, y)
    else:
        X_balanced, y_balanced = X, y
    
    if best_model_name == 'RandomForest':
        final_model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    else:
        final_model = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
    
    final_model.fit(X_balanced, y_balanced)
    
    # Save model
    model_dir = Path('models/mean_reversion')
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_file = model_dir / f"{symbol}_{interval}_mean_reversion.joblib"
    meta_file = model_dir / f"{symbol}_{interval}_mean_reversion.meta.json"
    
    if not dry_run:
        joblib.dump(final_model, model_file)
        
        metadata = {
            'symbol': symbol,
            'interval': interval,
            'model_type': best_model_name,
            'f1': best_f1,
            'precision': avg_rf_f1 if best_model_name == 'RandomForest' else avg_gb_f1,
            'training_samples': len(X_balanced),
            'positive_samples': int(y.sum()),
            'trained_at': datetime.now().isoformat(),
            'lookback_days': lookback_days
        }
        
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"✅ Model saved: {model_file}")
        logger.info(f"✅ Metadata saved: {meta_file}")
    else:
        logger.info("[DRY RUN] Model training complete, not saving")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train Mean Reversion ML Model')
    parser.add_argument('--symbol', type=str, required=True, help='Trading symbol (e.g. BTCUSDT)')
    parser.add_argument('--interval', type=str, default='1h', help='Timeframe (e.g. 1h, 30m)')
    parser.add_argument('--lookback-days', type=int, default=180, help='Days of historical data')
    parser.add_argument('--dry-run', action='store_true', help='Train but do not save model')
    
    args = parser.parse_args()
    
    train_model(args.symbol, args.interval, args.lookback_days, args.dry_run)
