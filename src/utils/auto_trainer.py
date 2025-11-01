"""
Intelligent Auto-Trainer for Trading Bot

Automatically discovers top trading pairs and trains ML models:
- Fetches top USDT pairs by 24h volume
- Trains models for promising pairs
- Retrains models periodically (weekly)
- Runs continuously in background
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import os
import sys
import subprocess
from pathlib import Path

# Add src to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance.client import Client
import json

logger = logging.getLogger(__name__)


class AutoTrainer:
    """Automatically discovers and trains ML models for top trading pairs"""
    
    def __init__(self, config):
        self.config = config
        self.client = Client(
            config.api_key,
            config.api_secret,
            testnet=(config.trading_mode == 'testnet')
        )
        
        # Auto-training settings
        self.min_volume_usdt = 1_000_000  # Minimum 24h volume (1M USDT - wider coverage)
        self.max_pairs = 200  # Train top 200 pairs (all liquid pairs)
        self.retrain_interval_days = 7  # Retrain weekly
        self.lookback_days = 90  # 90 days of data
        self.timeframe = '15m'  # 15-minute candles
        
        # Track trained models
        self.trained_pairs = {}
        self.load_training_history()
        
        logger.info("AutoTrainer initialized")
    
    def load_training_history(self):
        """Load history of trained models"""
        history_file = 'models/training_history.json'
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.trained_pairs = json.load(f)
                logger.info(f"Loaded training history: {len(self.trained_pairs)} pairs")
            except Exception as e:
                logger.error(f"Failed to load training history: {e}")
                self.trained_pairs = {}
    
    def save_training_history(self):
        """Save training history to disk"""
        history_file = 'models/training_history.json'
        os.makedirs('models', exist_ok=True)
        try:
            with open(history_file, 'w') as f:
                json.dump(self.trained_pairs, f, indent=2)
            logger.info("Training history saved")
        except Exception as e:
            logger.error(f"Failed to save training history: {e}")
    
    def get_top_usdt_pairs(self) -> List[Dict]:
        """
        Fetch top USDT trading pairs by 24h volume
        
        Returns:
            List of dicts with symbol, volume, price_change
        """
        logger.info("Fetching top USDT pairs from Binance...")
        
        try:
            # Get 24h ticker stats for all symbols
            tickers = self.client.get_ticker()
            
            # Filter for USDT pairs with sufficient volume
            usdt_pairs = []
            for ticker in tickers:
                symbol = ticker['symbol']
                
                # Only USDT pairs
                if not symbol.endswith('USDT'):
                    continue
                
                # Skip stablecoins and leveraged tokens
                skip_coins = ['USDC', 'BUSD', 'TUSD', 'DAI', 'UP', 'DOWN', 'BULL', 'BEAR']
                if any(coin in symbol for coin in skip_coins):
                    continue
                
                try:
                    volume = float(ticker['quoteVolume'])
                    price_change = float(ticker['priceChangePercent'])
                    
                    # Filter by minimum volume
                    if volume >= self.min_volume_usdt:
                        usdt_pairs.append({
                            'symbol': symbol,
                            'volume': volume,
                            'price_change': price_change,
                            'last_price': float(ticker['lastPrice'])
                        })
                except (ValueError, KeyError):
                    continue
            
            # Sort by volume (highest first)
            usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
            
            # Take top N pairs
            top_pairs = usdt_pairs[:self.max_pairs]
            
            logger.info(f"Found {len(top_pairs)} top USDT pairs")
            for i, pair in enumerate(top_pairs[:10], 1):
                logger.info(
                    f"  {i}. {pair['symbol']}: "
                    f"${pair['volume']:,.0f} volume, "
                    f"{pair['price_change']:+.2f}% change"
                )
            
            return top_pairs
            
        except Exception as e:
            logger.error(f"Failed to fetch top pairs: {e}")
            return []
    
    def should_train_pair(self, symbol: str) -> bool:
        """
        Check if a pair needs training/retraining
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            True if training is needed
        """
        # Never trained before
        if symbol not in self.trained_pairs:
            return True
        
        # Check if model is old
        last_trained = self.trained_pairs[symbol].get('last_trained')
        if not last_trained:
            return True
        
        try:
            last_trained_date = datetime.fromisoformat(last_trained)
            days_since_training = (datetime.now() - last_trained_date).days
            
            if days_since_training >= self.retrain_interval_days:
                logger.info(f"{symbol} model is {days_since_training} days old, needs retraining")
                return True
        except Exception as e:
            logger.error(f"Error checking training date for {symbol}: {e}")
            return True
        
        return False
    
    async def train_pair(self, symbol: str) -> bool:
        """
        Train ML model for a specific pair
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            True if training succeeded
        """
        logger.info(f"Training model for {symbol} ({self.timeframe}, {self.lookback_days} days)")
        
        try:
            # Run training script as subprocess (mean reversion model)
            cmd = [
                sys.executable, '-m', 'src.utils.train_mean_reversion',
                '--symbol', symbol,
                '--interval', self.timeframe,
                '--lookback-days', str(self.lookback_days)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes timeout per model
            )
            
            if result.returncode == 0:
                # Training succeeded - check metadata
                meta_file = Path(f'models/mean_reversion/{symbol}_{self.timeframe}_mean_reversion.meta.json')
                if meta_file.exists():
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    # Update training history
                    self.trained_pairs[symbol] = {
                        'last_trained': datetime.now().isoformat(),
                        'timeframe': self.timeframe,
                        'lookback_days': self.lookback_days,
                        'accuracy': meta.get('accuracy'),
                        'f1_score': meta.get('f1')
                    }
                    self.save_training_history()
                    
                    logger.info(
                        f"✓ {symbol} trained successfully: "
                        f"{meta.get('accuracy', 0)*100:.1f}% accuracy, "
                        f"{meta.get('f1', 0)*100:.1f}% F1"
                    )
                    return True
                else:
                    logger.error(f"✗ {symbol} training completed but no metadata found")
                    return False
            else:
                logger.error(f"✗ {symbol} training failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"✗ {symbol} training timed out (>10 minutes)")
            return False
        except Exception as e:
            logger.error(f"✗ {symbol} training error: {e}")
            return False
    
    async def auto_train_cycle(self):
        """
        Run one complete auto-training cycle:
        1. Discover top pairs
        2. Train/retrain models as needed
        """
        logger.info("=" * 60)
        logger.info("Starting auto-training cycle")
        logger.info("=" * 60)
        
        # Get top trading pairs
        top_pairs = self.get_top_usdt_pairs()
        
        if not top_pairs:
            logger.warning("No pairs found for training")
            return
        
        # Train pairs that need it
        trained_count = 0
        skipped_count = 0
        
        for pair_info in top_pairs:
            symbol = pair_info['symbol']
            
            if self.should_train_pair(symbol):
                success = await self.train_pair(symbol)
                if success:
                    trained_count += 1
                
                # Sleep between trainings to avoid rate limits
                await asyncio.sleep(10)
            else:
                logger.info(f"Skipping {symbol} (model is fresh)")
                skipped_count += 1
        
        logger.info("=" * 60)
        logger.info(f"Auto-training cycle complete: {trained_count} trained, {skipped_count} skipped")
        logger.info("=" * 60)
    
    async def run_forever(self):
        """
        Run auto-trainer continuously
        - Initial training for all top pairs
        - Recheck every 24 hours
        """
        logger.info("🤖 Auto-Trainer starting continuous operation")
        
        while True:
            try:
                # Run training cycle
                await self.auto_train_cycle()
                
                # Sleep for 24 hours before next cycle
                logger.info("Sleeping for 24 hours until next training cycle...")
                await asyncio.sleep(24 * 60 * 60)
                
            except KeyboardInterrupt:
                logger.info("Auto-Trainer stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in auto-trainer: {e}", exc_info=True)
                logger.info("Sleeping for 1 hour before retry...")
                await asyncio.sleep(60 * 60)


async def main():
    """Run auto-trainer standalone"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/auto_trainer.log'),
            logging.StreamHandler()
        ]
    )
    
    # Load config
    from config.config import Config
    config = Config()
    
    # Create and run auto-trainer
    trainer = AutoTrainer(config)
    await trainer.run_forever()


if __name__ == '__main__':
    asyncio.run(main())
