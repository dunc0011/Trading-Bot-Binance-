#!/usr/bin/env python3
"""
FIXED ML Model Retraining Script
- Recent 30-day data only
- Strict time-based train/test split
- Realistic profit targets (0.5% within 2h on 5m = 24 candles)
- All features properly lagged
- Walk-forward validation
"""
import subprocess
import sys
from pathlib import Path

# Top liquid pairs to retrain (avoiding blacklisted ones)
PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT', 'ATOMUSDT',
    'LINKUSDT', 'NEARUSDT', 'UNIUSDT', 'AAVEUSDT', 'LDOUSDT',
    'ICPUSDT', 'FILUSDT', 'SEIUSDT', 'HBARUSDT', 'CRVUSDT',
    'SUSHIUSDT', 'CAKEUSDT', 'RUNEUSDT', 'APEUSDT', 'GALAUSDT'
]

# Fixed training parameters
INTERVAL = '5m'
LOOKBACK_DAYS = 30  # Recent data only (not 90+)
PROFIT_TARGET = 0.005  # 0.5% minimum profit
STOP_LOSS = 0.01  # 1% stop loss
MAX_HOLDING = 24  # 2 hours on 5m (24 candles)

def train_symbol(symbol):
    """Train a single symbol with fixed parameters"""
    print(f"\n{'='*80}")
    print(f"Training {symbol} on {INTERVAL} with last {LOOKBACK_DAYS} days")
    print(f"{'='*80}\n")
    
    cmd = [
        'python', '-m', 'src.utils.train_advanced_model',
        '--symbol', symbol,
        '--interval', INTERVAL,
        '--lookback-days', str(LOOKBACK_DAYS),
        '--profit-target', str(PROFIT_TARGET),
        '--stop-loss', str(STOP_LOSS),
        '--max-holding', str(MAX_HOLDING),
        '--log-level', 'INFO'
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {symbol} trained successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {symbol} training failed: {e}")
        return False

def main():
    """Train all pairs"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║         FIXED ML MODEL RETRAINING - ALL PAIRS                ║
╠══════════════════════════════════════════════════════════════╣
║ ✓ Recent 30-day data only (not stale 90+ days)             ║
║ ✓ Strict time-based split (no data leakage)                ║
║ ✓ Realistic targets: 0.5% profit within 2 hours            ║
║ ✓ All features lagged by 1+ candles                        ║
║ ✓ Walk-forward validation on unseen data                   ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    print(f"\nTraining {len(PAIRS)} pairs...")
    print(f"Parameters: {INTERVAL} | {LOOKBACK_DAYS}d | TP={PROFIT_TARGET*100}% | SL={STOP_LOSS*100}% | MaxHold={MAX_HOLDING}")
    
    input("\nPress ENTER to start training (or Ctrl+C to cancel)...")
    
    success_count = 0
    failed_symbols = []
    
    for i, symbol in enumerate(PAIRS, 1):
        print(f"\n[{i}/{len(PAIRS)}] Training {symbol}...")
        
        if train_symbol(symbol):
            success_count += 1
        else:
            failed_symbols.append(symbol)
    
    # Summary
    print(f"\n{'='*80}")
    print(f"TRAINING COMPLETE")
    print(f"{'='*80}")
    print(f"✅ Successfully trained: {success_count}/{len(PAIRS)}")
    if failed_symbols:
        print(f"❌ Failed: {', '.join(failed_symbols)}")
    print(f"\nModels saved to: models/advanced_ml/")
    print(f"\nRestart the bot to load new models:")
    print(f"  docker-compose restart web-ui")

if __name__ == '__main__':
    main()
