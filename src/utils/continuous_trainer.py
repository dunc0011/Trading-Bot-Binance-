"""
Continuous Model Training Service
Automatically retrains ML models for all configured pairs on a schedule
"""
import logging
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Event
from typing import List, Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.config import Config
from src.utils.train_advanced_model import main as train_advanced_main

logger = logging.getLogger(__name__)


class ContinuousTrainer:
    """Continuously retrains ML models for all trading pairs"""
    
    def __init__(self, config: Config, retrain_interval_hours: int = 24):
        """
        Args:
            config: Bot configuration
            retrain_interval_hours: Hours between retraining cycles (default 24)
        """
        self.config = config
        self.retrain_interval = timedelta(hours=retrain_interval_hours)
        self.symbols = self._get_all_symbols()
        self.interval = config.timeframe
        self.lookback_days = 90
        self.optimize = True  # Always use optimization
        self.running = False
        self.stop_event = Event()
        self.thread = None
        self.last_train_times: Dict[str, datetime] = {}
        
        logger.info(f"ContinuousTrainer initialized for {len(self.symbols)} pairs")
        logger.info(f"Retrain interval: {retrain_interval_hours}h, Interval: {self.interval}")
    
    def _get_all_symbols(self) -> List[str]:
        """Get all symbols to train from config or auto-discover from Binance"""
        # Check if SYMBOLS is configured (comma-separated)
        symbols_str = getattr(self.config, 'symbols', None)
        if symbols_str and symbols_str.lower() != 'all':
            symbols = [s.strip() for s in symbols_str.split(',')]
            logger.info(f"Using configured symbols: {symbols}")
            return symbols
        
        # Auto-discover ALL USDT pairs from Binance
        logger.info("Auto-discovering all USDT pairs from Binance...")
        try:
            from binance.client import Client
            
            # Initialize Binance client
            if self.config.trading_mode == "testnet":
                client = Client(self.config.api_key, self.config.api_secret, testnet=True)
            else:
                client = Client(self.config.api_key, self.config.api_secret)
            
            # Get 24h ticker data for all symbols
            tickers = client.get_ticker()
            
            # Filter criteria
            skip_tokens = ['USDC', 'BUSD', 'TUSD', 'DAI', 'USDP', 'FDUSD', 
                          'UP', 'DOWN', 'BULL', 'BEAR']  # Skip stablecoins and leveraged tokens
            min_volume = getattr(self.config, 'min_volume_usdt', 1_000_000)  # Default $1M daily volume
            
            valid_symbols = []
            
            for ticker in tickers:
                symbol = ticker['symbol']
                
                # Only USDT pairs
                if not symbol.endswith('USDT'):
                    continue
                
                # Skip stablecoins and leveraged tokens
                if any(token in symbol for token in skip_tokens):
                    continue
                
                try:
                    volume = float(ticker['quoteVolume'])
                    
                    # Only pairs with sufficient volume
                    if volume >= min_volume:
                        valid_symbols.append(symbol)
                except (ValueError, KeyError):
                    continue
            
            # Sort by volume (highest first)
            valid_symbols_with_volume = []
            for symbol in valid_symbols:
                ticker_data = next((t for t in tickers if t['symbol'] == symbol), None)
                if ticker_data:
                    volume = float(ticker_data['quoteVolume'])
                    valid_symbols_with_volume.append((symbol, volume))
            
            valid_symbols_with_volume.sort(key=lambda x: x[1], reverse=True)
            sorted_symbols = [s[0] for s in valid_symbols_with_volume]
            
            logger.info(f"Discovered {len(sorted_symbols)} USDT pairs with >$1M volume")
            logger.info(f"Top 10: {', '.join(sorted_symbols[:10])}")
            
            return sorted_symbols
        
        except Exception as e:
            logger.error(f"Failed to auto-discover pairs: {e}")
            logger.warning("Falling back to default top 20 pairs")
            
            # Fallback to extended default list
            return [
                'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
                'ADAUSDT', 'DOGEUSDT', 'DOTUSDT', 'MATICUSDT', 'LTCUSDT',
                'AVAXUSDT', 'LINKUSDT', 'ATOMUSDT', 'UNIUSDT', 'ETCUSDT',
                'FILUSDT', 'APTUSDT', 'ARBUSDT', 'OPUSDT', 'NEARUSDT'
            ]
    
    def should_retrain(self, symbol: str) -> bool:
        """Check if symbol should be retrained"""
        if symbol not in self.last_train_times:
            return True
        
        time_since_last = datetime.now() - self.last_train_times[symbol]
        return time_since_last >= self.retrain_interval
    
    def train_symbol(self, symbol: str) -> Dict:
        """Train a single symbol and return results"""
        logger.info(f"[ContinuousTrainer] Starting training for {symbol}")
        
        try:
            # Prepare arguments
            old_argv = sys.argv
            sys.argv = [
                'train_advanced_ml_model',
                '--symbol', symbol,
                '--interval', self.interval,
                '--lookback-days', str(self.lookback_days)
            ]
            if self.optimize:
                sys.argv.append('--optimize')
            
            # Train model
            start_time = time.time()
            train_advanced_main()
            duration = time.time() - start_time
            
            # Restore argv
            sys.argv = old_argv
            
            # Update last train time
            self.last_train_times[symbol] = datetime.now()
            
            # Read model metadata
            meta_path = Path(f'models/ml_ema/{symbol}_{self.interval}_ml_ema.meta.json')
            if meta_path.exists():
                import json
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    
                logger.info(
                    f"[ContinuousTrainer] ✓ {symbol} trained successfully in {duration:.1f}s - "
                    f"F1: {meta.get('f1', 0):.3f}, Acc: {meta.get('accuracy', 0):.3f}"
                )
                
                return {
                    'symbol': symbol,
                    'success': True,
                    'duration': duration,
                    'f1_score': meta.get('f1'),
                    'accuracy': meta.get('accuracy'),
                    'model_type': meta.get('model')
                }
            else:
                logger.warning(f"[ContinuousTrainer] {symbol} trained but no metadata found")
                return {
                    'symbol': symbol,
                    'success': True,
                    'duration': duration
                }
        
        except Exception as e:
            logger.error(f"[ContinuousTrainer] Failed to train {symbol}: {e}", exc_info=True)
            return {
                'symbol': symbol,
                'success': False,
                'error': str(e)
            }
    
    def training_cycle(self):
        """Run one complete training cycle for all symbols"""
        logger.info(f"[ContinuousTrainer] Starting training cycle for {len(self.symbols)} pairs")
        cycle_start = time.time()
        results = []
        
        for idx, symbol in enumerate(self.symbols, 1):
            if self.stop_event.is_set():
                logger.info("[ContinuousTrainer] Stop requested, ending cycle early")
                break
            
            if not self.should_retrain(symbol):
                logger.info(
                    f"[ContinuousTrainer] [{idx}/{len(self.symbols)}] {symbol} - "
                    f"Skipping (trained {datetime.now() - self.last_train_times[symbol]} ago)"
                )
                continue
            
            logger.info(f"[ContinuousTrainer] [{idx}/{len(self.symbols)}] Training {symbol}...")
            result = self.train_symbol(symbol)
            results.append(result)
        
        cycle_duration = time.time() - cycle_start
        success_count = sum(1 for r in results if r['success'])
        
        logger.info(
            f"[ContinuousTrainer] Cycle complete in {cycle_duration:.1f}s - "
            f"{success_count}/{len(results)} successful"
        )
        
        return results
    
    def run(self):
        """Main loop - runs training cycles continuously"""
        logger.info("[ContinuousTrainer] Starting continuous training service")
        
        # Check if models already exist
        from pathlib import Path
        models_exist = len(list(Path('models/advanced_ml').glob('*.joblib'))) > 0
        
        if models_exist:
            logger.info("[ContinuousTrainer] Models already exist, skipping initial training")
            logger.info("[ContinuousTrainer] Will retrain in background as models become stale")
        else:
            # Initial training for all symbols
            logger.info("[ContinuousTrainer] No models found, running initial training cycle...")
            self.training_cycle()
        
        # Continuous retraining loop
        while not self.stop_event.is_set():
            try:
                # Calculate time until next cycle
                if self.last_train_times:
                    oldest_train = min(self.last_train_times.values())
                    time_until_next = (oldest_train + self.retrain_interval) - datetime.now()
                    
                    if time_until_next.total_seconds() > 0:
                        wait_time = min(time_until_next.total_seconds(), 3600)  # Check hourly
                        logger.info(
                            f"[ContinuousTrainer] Next cycle in {time_until_next.total_seconds() / 3600:.1f}h"
                        )
                        if self.stop_event.wait(wait_time):
                            break
                        continue
                
                # Run training cycle
                self.training_cycle()
            
            except Exception as e:
                logger.error(f"[ContinuousTrainer] Error in training loop: {e}", exc_info=True)
                # Wait before retrying
                if self.stop_event.wait(300):  # 5 minutes
                    break
        
        logger.info("[ContinuousTrainer] Stopped")
    
    def start(self):
        """Start continuous training in background thread"""
        if self.running:
            logger.warning("[ContinuousTrainer] Already running")
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = Thread(target=self.run, daemon=True, name="ContinuousTrainer")
        self.thread.start()
        logger.info("[ContinuousTrainer] Started in background thread")
    
    def stop(self):
        """Stop continuous training"""
        if not self.running:
            return
        
        logger.info("[ContinuousTrainer] Stopping...")
        self.stop_event.set()
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        
        logger.info("[ContinuousTrainer] Stopped")
    
    def get_status(self) -> Dict:
        """Get current status of continuous trainer"""
        return {
            'running': self.running,
            'total_symbols': len(self.symbols),
            'symbols': self.symbols,
            'retrain_interval_hours': self.retrain_interval.total_seconds() / 3600,
            'last_train_times': {
                symbol: time.isoformat()
                for symbol, time in self.last_train_times.items()
            },
            'next_trains': {
                symbol: (time + self.retrain_interval).isoformat()
                for symbol, time in self.last_train_times.items()
            }
        }


def main():
    """Standalone continuous trainer"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Continuous ML Model Trainer')
    parser.add_argument('--interval-hours', type=int, default=24,
                       help='Hours between retraining cycles (default: 24)')
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/continuous_trainer.log'),
            logging.StreamHandler()
        ]
    )
    
    # Load config
    config = Config()
    
    # Create and start trainer
    trainer = ContinuousTrainer(config, retrain_interval_hours=args.interval_hours)
    
    try:
        trainer.start()
        # Keep main thread alive
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        trainer.stop()


if __name__ == '__main__':
    main()
