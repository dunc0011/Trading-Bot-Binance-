"""
Advanced Model Training Script
Combines:
- Advanced feature engineering (50+ features)
- Triple barrier labeling
- XGBoost/LightGBM with Optuna optimization
- Feature selection
- Proper evaluation metrics
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from binance.client import Client
from dotenv import load_dotenv

from config.config import Config
from utils.advanced_features import AdvancedFeatureEngine
from utils.triple_barrier import TripleBarrierLabeler, optimize_holding_period
from utils.advanced_ml_trainer import AdvancedMLTrainer
from utils.market_aware_features import add_market_aware_features


def setup_logging(level='INFO'):
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/advanced_ml_training.log')
        ]
    )
    return logging.getLogger(__name__)


def fetch_historical_data(client, symbol, interval, lookback_days):
    """
    Fetch historical kline data from Binance
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Fetching {lookback_days} days of {symbol} {interval} data...")
    
    interval_minutes = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720,
        '1d': 1440
    }
    
    minutes_per_candle = interval_minutes.get(interval, 60)
    total_candles = (lookback_days * 24 * 60) // minutes_per_candle
    
    all_klines = []
    limit_per_request = 1000
    
    end_time = datetime.now()
    
    while len(all_klines) < total_candles:
        try:
            klines = client.get_historical_klines(
                symbol=symbol,
                interval=interval,
                start_str=str(int((end_time - timedelta(days=lookback_days)).timestamp() * 1000)),
                end_str=str(int(end_time.timestamp() * 1000)),
                limit=limit_per_request
            )
            
            if not klines:
                break
            
            all_klines.extend(klines)
            
            if len(klines) < limit_per_request:
                break
            
            end_time = datetime.fromtimestamp(klines[0][0] / 1000)
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            break
    
    df = pd.DataFrame(all_klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp')
    
    logger.info(f"Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    
    return df


def main():
    """Main training function"""
    parser = argparse.ArgumentParser(description='Train Advanced ML Trading Model')
    parser.add_argument('--symbol', type=str, default='BTCUSDT',
                       help='Trading pair (default: BTCUSDT)')
    parser.add_argument('--interval', type=str, default='15m',
                       help='Timeframe (default: 15m)')
    parser.add_argument('--lookback-days', type=int, default=180,
                       help='Days of historical data (default: 180)')
    parser.add_argument('--model-dir', type=str, default='models/advanced_ml',
                       help='Model output directory (default: models/advanced_ml)')
    parser.add_argument('--profit-target', type=float, default=0.02,
                       help='Triple barrier profit target (default: 0.02 = 2%%)')
    parser.add_argument('--stop-loss', type=float, default=0.01,
                       help='Triple barrier stop loss (default: 0.01 = 1%%)')
    parser.add_argument('--max-holding', type=int, default=24,
                       help='Max holding periods for triple barrier (default: 24)')
    parser.add_argument('--optimize-hyperparams', action='store_true',
                       help='Use Optuna for hyperparameter optimization (slower but better)')
    parser.add_argument('--n-trials', type=int, default=50,
                       help='Number of Optuna trials (default: 50)')
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level (default: INFO)')
    
    args = parser.parse_args()
    
    logger = setup_logging(args.log_level)
    logger.info("=" * 80)
    logger.info("ADVANCED ML MODEL TRAINING")
    logger.info("=" * 80)
    logger.info(f"Symbol: {args.symbol}")
    logger.info(f"Interval: {args.interval}")
    logger.info(f"Lookback: {args.lookback_days} days")
    logger.info(f"Model Dir: {args.model_dir}")
    logger.info(f"Triple Barrier: TP={args.profit_target*100}%, SL={args.stop_loss*100}%, Max Hold={args.max_holding}")
    logger.info(f"Hyperparameter Optimization: {args.optimize_hyperparams}")
    logger.info("=" * 80)
    
    # Load environment
    load_dotenv()
    config = Config()
    
    # Initialize Binance client
    if config.trading_mode == "testnet":
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)
    
    logger.info("Connected to Binance API")
    
    # ==== STEP 1: Fetch Historical Data ====
    try:
        df = fetch_historical_data(
            client=client,
            symbol=args.symbol,
            interval=args.interval,
            lookback_days=args.lookback_days
        )
    except Exception as e:
        logger.error(f"Failed to fetch historical data: {e}", exc_info=True)
        return 1
    
    # ==== STEP 2: Build Advanced Features ====
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Building Advanced Features")
    logger.info("=" * 80)
    
    # Add market-aware contextual features
    logger.info("Adding market-aware features (multi-timeframe, volume, regime)...")
    try:
        df = add_market_aware_features(df.reset_index(), client, args.symbol, args.interval)
        df = df.set_index('timestamp')
        logger.info(f"Market-aware features added: multi-timeframe alignment, volume microstructure, regime detection")
    except Exception as e:
        logger.warning(f"Could not add market-aware features: {e}")
    
    feature_engine = AdvancedFeatureEngine()
    
    try:
        features = feature_engine.build_features(df)
        logger.info(f"Created {len(features.columns)} features (base + market-aware): {list(features.columns[:20])}... and {len(features.columns)-20} more")
    except Exception as e:
        logger.error(f"Feature engineering failed: {e}", exc_info=True)
        return 1
    
    # ==== STEP 3: Apply Triple Barrier Labeling ====
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Applying Triple Barrier Labeling")
    logger.info("=" * 80)
    
    labeler = TripleBarrierLabeler(
        profit_target=args.profit_target,
        stop_loss=args.stop_loss,
        max_holding_periods=args.max_holding
    )
    
    try:
        df_labeled = labeler.label_data(df, volatility_adj=True)
        logger.info(f"Labeled {len(df_labeled)} samples")
    except Exception as e:
        logger.error(f"Labeling failed: {e}", exc_info=True)
        return 1
    
    # ==== STEP 4: Align Features with Labels ====
    # Features are already lagged, so align with labels
    common_index = features.index.intersection(df_labeled.index)
    X = features.loc[common_index]
    y = df_labeled.loc[common_index, 'label'].astype(int)
    
    logger.info(f"Final dataset: {len(X)} samples with {len(X.columns)} features")
    logger.info(f"Label distribution: {y.value_counts().to_dict()}")
    
    if len(X) < 100:
        logger.error("Insufficient data after feature engineering and labeling")
        return 1
    
    # ==== STEP 5: Train Advanced ML Models ====
    logger.info("\n" + "=" * 80)
    logger.info("STEP 5: Training Advanced ML Models")
    logger.info("=" * 80)
    
    trainer = AdvancedMLTrainer(
        model_dir=args.model_dir,
        symbol=args.symbol,
        interval=args.interval,
        optimize_hyperparams=args.optimize_hyperparams,
        n_trials=args.n_trials
    )
    
    try:
        model, metadata = trainer.train_models(X, y)
        trainer.save_model(model, metadata)
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return 1
    
    # ==== FINAL REPORT ====
    logger.info("\n" + "=" * 80)
    logger.info("TRAINING COMPLETE!")
    logger.info("=" * 80)
    logger.info(f"Model: {metadata['model_name']}")
    logger.info(f"F1 Score: {metadata['f1']:.4f}")
    logger.info(f"Precision: {metadata['precision']:.4f}")
    logger.info(f"Recall: {metadata['recall']:.4f}")
    logger.info(f"Accuracy: {metadata['accuracy']:.4f}")
    if 'auc' in metadata:
        logger.info(f"AUC-ROC: {metadata['auc']:.4f}")
    logger.info(f"Features Selected: {metadata['n_features']}/{len(X.columns)}")
    logger.info(f"Training Samples: {metadata['samples']}")
    logger.info(f"Model saved to: {trainer.model_path}")
    logger.info("=" * 80)
    
    # Expected performance estimate
    if metadata['f1'] > 0.6:
        logger.info("✅ EXCELLENT: Model shows strong predictive power")
    elif metadata['f1'] > 0.55:
        logger.info("✅ GOOD: Model should be profitable with proper risk management")
    elif metadata['f1'] > 0.5:
        logger.info("⚠️  MARGINAL: Model is better than random but needs careful testing")
    else:
        logger.info("❌ POOR: Model unlikely to be profitable - consider more data or different features")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
