"""
Training script for ML EMA trading model
Can be run standalone to train models on historical data
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from binance.client import Client
from dotenv import load_dotenv

from config.config import Config
from utils.ml_model_manager import MLModelManager


def setup_logging(level='INFO'):
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/ml_training.log')
        ]
    )
    return logging.getLogger(__name__)


def fetch_historical_data(client, symbol, interval, lookback_days):
    """
    Fetch historical kline data from Binance
    
    Args:
        client: Binance client
        symbol: Trading pair (e.g., 'ETHUSDT')
        interval: Timeframe (e.g., '1m', '1h')
        lookback_days: Number of days to fetch
    
    Returns:
        DataFrame with OHLCV data
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Fetching {lookback_days} days of {symbol} {interval} data...")
    
    # Calculate how many candles we need
    interval_minutes = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720,
        '1d': 1440
    }
    
    minutes_per_candle = interval_minutes.get(interval, 60)
    total_candles = (lookback_days * 24 * 60) // minutes_per_candle
    
    # Binance limits to 1000 per request, so we need multiple requests
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
            
            # Update end_time for next batch
            end_time = datetime.fromtimestamp(klines[0][0] / 1000)
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            break
    
    # Convert to DataFrame
    df = pd.DataFrame(all_klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    
    # Convert types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp')
    
    logger.info(f"Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    
    return df


def main():
    """Main training function"""
    parser = argparse.ArgumentParser(description='Train ML EMA trading model')
    parser.add_argument('--symbol', type=str, default='ETHUSDT',
                       help='Trading pair (default: ETHUSDT)')
    parser.add_argument('--interval', type=str, default='1h',
                       help='Timeframe (default: 1h)')
    parser.add_argument('--lookback-days', type=int, default=90,
                       help='Days of historical data (default: 90)')
    parser.add_argument('--model-dir', type=str, default='models/ml_ema',
                       help='Model output directory (default: models/ml_ema)')
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level (default: INFO)')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.log_level)
    logger.info("=" * 60)
    logger.info("ML EMA Model Training")
    logger.info("=" * 60)
    logger.info(f"Symbol: {args.symbol}")
    logger.info(f"Interval: {args.interval}")
    logger.info(f"Lookback: {args.lookback_days} days")
    logger.info(f"Model Dir: {args.model_dir}")
    logger.info("=" * 60)
    
    # Load environment
    load_dotenv()
    config = Config()
    
    # Override config with command line args
    config.symbol = args.symbol
    config.timeframe = args.interval
    config.ml_model_dir = args.model_dir
    
    # Initialize Binance client
    if config.trading_mode == "testnet":
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)
    
    logger.info("Connected to Binance API")
    
    # Fetch historical data
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
    
    # Initialize ML Manager
    ml_manager = MLModelManager(
        config=config,
        model_dir=args.model_dir,
        symbol=args.symbol,
        interval=args.interval,
        logger=logger
    )
    
    # Train model
    try:
        logger.info("Starting model training...")
        metadata = ml_manager.train_and_persist(df)
        
        logger.info("=" * 60)
        logger.info("Training Complete!")
        logger.info("=" * 60)
        logger.info(f"Best Model: {metadata['model']}")
        logger.info(f"F1 Score: {metadata['f1']:.4f}")
        logger.info(f"Precision: {metadata['precision']:.4f}")
        logger.info(f"Recall: {metadata['recall']:.4f}")
        logger.info(f"Accuracy: {metadata['accuracy']:.4f}")
        logger.info(f"Training Samples: {metadata['samples']}")
        logger.info(f"Model saved to: {ml_manager.model_path}")
        logger.info(f"Metadata saved to: {ml_manager.meta_path}")
        logger.info("=" * 60)
        
        return 0
    
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
