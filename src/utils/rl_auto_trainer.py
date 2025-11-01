"""
Automated RL Training System
Continuously trains RL agents for top trading pairs by volume
"""
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import List, Dict

from binance.client import Client
from config.config import Config
from utils.rl_agent import train_rl_agent_for_symbol


class RLAutoTrainer:
    """
    Automatically discover and train RL agents for top USDT pairs
    
    Features:
    - Discovers top N pairs by 24h volume
    - Trains RL models for each pair
    - Retrains weekly to keep models fresh
    - Runs continuously in background
    """
    
    def __init__(self, config: Config = None, max_pairs: int = 10, timeframe: str = '5m', 
                 lookback_days: int = 90, total_timesteps: int = 100000):
        self.config = config or Config()
        self.logger = logging.getLogger(__name__)
        
        # Configuration (allow override via parameters)
        self.min_volume_usdt = 10_000_000  # Min 24h volume (10M USDT)
        self.max_pairs = max_pairs
        self.retrain_interval_days = 3  # Retrain every 3 days (faster adaptation)
        self.lookback_days = lookback_days
        self.timeframe = timeframe
        self.total_timesteps = total_timesteps
        
        # State tracking
        self.training_history_file = Path('models/rl_training_history.json')
        self.training_history = self._load_training_history()
        
        # Binance client
        if self.config.trading_mode == "testnet":
            self.client = Client(self.config.api_key, self.config.api_secret, testnet=True)
        else:
            self.client = Client(self.config.api_key, self.config.api_secret)
        
        self.logger.info("🤖 RL Auto-Trainer initialized")
    
    def _load_training_history(self) -> Dict:
        """Load training history from disk"""
        if self.training_history_file.exists():
            with open(self.training_history_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_training_history(self):
        """Save training history to disk"""
        self.training_history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.training_history_file, 'w') as f:
            json.dump(self.training_history, f, indent=2)
    
    def discover_top_pairs(self) -> List[str]:
        """
        Discover top USDT pairs by 24h volume
        
        Returns:
            List of trading pairs
        """
        self.logger.info(f"🔍 Discovering top {self.max_pairs} USDT pairs...")
        
        try:
            # Get all USDT pairs
            tickers = self.client.get_ticker()
            usdt_pairs = [
                t for t in tickers 
                if t['symbol'].endswith('USDT') 
                and not any(x in t['symbol'] for x in ['UP', 'DOWN', 'BULL', 'BEAR'])  # Exclude leveraged tokens
            ]
            
            # Calculate volume in USDT
            for ticker in usdt_pairs:
                ticker['volume_usdt'] = float(ticker['quoteVolume'])
            
            # Filter by minimum volume
            filtered = [
                t for t in usdt_pairs 
                if t['volume_usdt'] >= self.min_volume_usdt
            ]
            
            # Sort by volume (highest first)
            filtered.sort(key=lambda x: x['volume_usdt'], reverse=True)
            
            # Take top N
            top_pairs = [t['symbol'] for t in filtered[:self.max_pairs]]
            
            self.logger.info(f"✅ Found {len(top_pairs)} pairs: {', '.join(top_pairs)}")
            
            for i, ticker in enumerate(filtered[:self.max_pairs], 1):
                volume_m = ticker['volume_usdt'] / 1_000_000
                self.logger.info(f"  {i}. {ticker['symbol']}: ${volume_m:.1f}M volume")
            
            return top_pairs
        
        except Exception as e:
            self.logger.error(f"Error discovering pairs: {e}")
            # Fallback to common pairs
            return ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
    
    def needs_training(self, symbol: str) -> bool:
        """
        Check if symbol needs (re)training
        
        Args:
            symbol: Trading pair
            
        Returns:
            True if training needed
        """
        key = f"{symbol}_{self.timeframe}"
        
        # Check if never trained
        if key not in self.training_history:
            self.logger.info(f"📝 {symbol}: Never trained")
            return True
        
        # Check if retrain interval passed
        last_trained = datetime.fromisoformat(self.training_history[key]['last_trained'])
        days_since = (datetime.now() - last_trained).days
        
        if days_since >= self.retrain_interval_days:
            self.logger.info(f"📝 {symbol}: Last trained {days_since} days ago (>= {self.retrain_interval_days})")
            return True
        
        self.logger.info(f"✓ {symbol}: Trained {days_since} days ago (fresh)")
        return False
    
    def train_pair(self, symbol: str):
        """
        Train RL agent for a specific pair
        
        Args:
            symbol: Trading pair
        """
        self.logger.info(f"🏋️ Training RL agent for {symbol} {self.timeframe}...")
        
        try:
            # Train using the existing training function
            agent, eval_stats = train_rl_agent_for_symbol(
                symbol=symbol,
                timeframe=self.timeframe,
                lookback_days=self.lookback_days,
                total_timesteps=self.total_timesteps
            )
            
            # Record training
            key = f"{symbol}_{self.timeframe}"
            self.training_history[key] = {
                'symbol': symbol,
                'timeframe': self.timeframe,
                'last_trained': datetime.now().isoformat(),
                'timesteps': self.total_timesteps,
                'evaluation': eval_stats
            }
            self._save_training_history()
            
            self.logger.info(
                f"✅ {symbol} RL training complete! "
                f"Return: {eval_stats['avg_return_pct']:.2f}%, "
                f"Sharpe: {eval_stats['avg_sharpe_ratio']:.2f}, "
                f"Win Rate: {eval_stats['avg_win_rate']*100:.1f}%"
            )
        
        except Exception as e:
            self.logger.error(f"❌ Failed to train {symbol}: {e}", exc_info=True)
    
    def train_all_pairs_once(self):
        """
        Train all top pairs once, ignoring retrain interval.
        Used for manual/UI-triggered batch training.
        """
        self.logger.info("=" * 80)
        self.logger.info("🚀 Starting Manual RL Training for Top Pairs")
        self.logger.info("=" * 80)
        
        # Discover top pairs
        top_pairs = self.discover_top_pairs()
        
        # Train all pairs
        for i, symbol in enumerate(top_pairs, 1):
            self.logger.info(f"[{i}/{len(top_pairs)}] Training {symbol}...")
            self.train_pair(symbol)
            
            # Sleep between training to avoid overload
            if i < len(top_pairs):
                self.logger.info("😴 Sleeping 60s before next training...")
                time.sleep(60)
        
        self.logger.info(f"✅ Batch training complete! Trained {len(top_pairs)} models")
    
    def run_training_cycle(self):
        """Run one training cycle for all pairs that need it"""
        self.logger.info("=" * 80)
        self.logger.info("🚀 Starting RL Auto-Trainer Cycle")
        self.logger.info("=" * 80)
        
        # Discover top pairs
        top_pairs = self.discover_top_pairs()
        
        # Train pairs that need it
        trained_count = 0
        for symbol in top_pairs:
            if self.needs_training(symbol):
                self.train_pair(symbol)
                trained_count += 1
                
                # Sleep between training to avoid overload
                if trained_count < len(top_pairs):
                    self.logger.info("😴 Sleeping 60s before next training...")
                    time.sleep(60)
        
        if trained_count == 0:
            self.logger.info("✨ All models are up to date!")
        else:
            self.logger.info(f"✅ Training cycle complete! Trained {trained_count} models")
    
    def run_forever(self, check_interval_hours: int = 24):
        """
        Run auto-trainer continuously
        
        Args:
            check_interval_hours: Hours between training cycles
        """
        self.logger.info(f"🔄 RL Auto-Trainer running (checking every {check_interval_hours}h)")
        
        while True:
            try:
                self.run_training_cycle()
                
                # Wait until next cycle
                self.logger.info(f"⏰ Sleeping for {check_interval_hours} hours...")
                time.sleep(check_interval_hours * 3600)
            
            except KeyboardInterrupt:
                self.logger.info("👋 RL Auto-Trainer stopped by user")
                break
            
            except Exception as e:
                self.logger.error(f"Error in training cycle: {e}", exc_info=True)
                self.logger.info("😴 Sleeping 1 hour before retry...")
                time.sleep(3600)


if __name__ == '__main__':
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config = Config()
    
    # Create and run auto-trainer
    trainer = RLAutoTrainer(config)
    trainer.run_forever(check_interval_hours=24)
