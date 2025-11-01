#!/usr/bin/env python3
"""
Discover and train ALL tradeable USDT pairs on Binance
Excludes stablecoins and low-volume pairs
"""
import sys
import os
import subprocess
import time
sys.path.insert(0, '/app')
from binance.client import Client
from config.config import Config

# Stablecoins to blacklist (never train these)
STABLECOIN_BLACKLIST = {
    'USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'BUSDUSDT', 
    'USDEUSDT', 'USDPUSDT', 'PAXUSDT', 'DAIUSDT',
    'FRAXUSDT', 'USDTUSDT'
}

# Known bad performers (optional - add pairs that consistently lose)
BAD_PERFORMERS = {
    'ZECUSDT', 'PEPEUSDT', 'FLOKIUSDT', 'PENDLEUSDT'
}

def get_all_usdt_pairs(min_volume_usdt=5_000_000):
    """
    Fetch all USDT trading pairs from Binance with sufficient volume
    
    Args:
        min_volume_usdt: Minimum 24h volume in USDT
        
    Returns:
        List of symbol strings
    """
    config = Config()
    
    if config.trading_mode == "testnet":
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)
    
    print(f"🔍 Fetching all USDT pairs from Binance...")
    
    # Get 24h ticker data
    tickers = client.get_ticker()
    
    usdt_pairs = []
    
    for ticker in tickers:
        symbol = ticker['symbol']
        
        # Must end with USDT
        if not symbol.endswith('USDT'):
            continue
        
        # Skip stablecoins
        if symbol in STABLECOIN_BLACKLIST:
            print(f"  ⊗ Skipping stablecoin: {symbol}")
            continue
        
        # Skip known bad performers
        if symbol in BAD_PERFORMERS:
            print(f"  ⊗ Skipping bad performer: {symbol}")
            continue
        
        # Check volume
        try:
            volume = float(ticker['quoteVolume'])
            
            if volume >= min_volume_usdt:
                usdt_pairs.append((symbol, volume))
                print(f"  ✓ {symbol}: ${volume:,.0f} 24h volume")
        except:
            continue
    
    # Sort by volume (highest first)
    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\n✅ Found {len(usdt_pairs)} tradeable USDT pairs")
    print(f"   (excluded {len(STABLECOIN_BLACKLIST)} stablecoins)")
    
    return [pair[0] for pair in usdt_pairs]


def model_exists(symbol, interval='30m'):
    """Check if model already exists"""
    from pathlib import Path
    model_file = Path(f'models/ml_ema/{symbol}_{interval}_ml_ema.joblib')
    return model_file.exists()

def train_model(symbol, interval='30m', lookback_days=90):
    """
    Train ML model for a single symbol
    
    Args:
        symbol: Trading pair (e.g. BTCUSDT)
        interval: Timeframe (30m, 1h, etc)
        lookback_days: Historical data lookback
        
    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*60}")
    print(f"📊 Training {symbol} ({interval}, {lookback_days} days)")
    print(f"{'='*60}")
    
    cmd = [
        'python', '-m', 'src.utils.train_ml_model',
        '--symbol', symbol,
        '--interval', interval,
        '--lookback-days', str(lookback_days),
        '--model-dir', 'models/ml_ema',
        '--log-level', 'INFO'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=False, text=True, cwd='/app')
        
        if result.returncode == 0:
            print(f"✅ {symbol} trained successfully\n")
            return True
        else:
            print(f"❌ {symbol} training failed\n")
            return False
    
    except Exception as e:
        print(f"❌ {symbol} error: {e}\n")
        return False


def main():
    """Main training loop"""
    
    print("="*60)
    print("🚀 TRAIN ALL BINANCE USDT PAIRS")
    print("="*60)
    print()
    
    # Get configuration from .env
    config = Config()
    interval = config.timeframe
    min_volume = 5_000_000  # $5M minimum
    lookback_days = 180  # 180 days for better pattern detection
    
    print(f"⚙️  Configuration:")
    print(f"   Timeframe: {interval}")
    print(f"   Min Volume: ${min_volume:,.0f}")
    print(f"   Lookback: {lookback_days} days")
    print()
    
    # Discover all pairs
    pairs = get_all_usdt_pairs(min_volume_usdt=min_volume)
    
    if not pairs:
        print("❌ No pairs found!")
        return
    
    print(f"\n{'='*60}")
    print(f"🎯 Training {len(pairs)} pairs...")
    print(f"   Estimated time: {len(pairs) * 2} minutes")
    print(f"{'='*60}\n")
    
    input("Press ENTER to start training (or Ctrl+C to cancel)...")
    
    # Train each pair
    successful = 0
    failed = 0
    skipped = 0
    start_time = time.time()
    
    for i, symbol in enumerate(pairs, 1):
        print(f"\n[{i}/{len(pairs)}] Processing {symbol}...")
        
        # Skip if model already exists
        if model_exists(symbol, interval=interval):
            print(f"⏭️  {symbol} already trained, skipping...")
            skipped += 1
            continue
        
        if train_model(symbol, interval=interval, lookback_days=lookback_days):
            successful += 1
        else:
            failed += 1
        
        # Small delay to avoid API rate limits
        if i < len(pairs):
            time.sleep(2)
    
    # Summary
    elapsed = time.time() - start_time
    elapsed_mins = elapsed / 60
    
    print("\n" + "="*60)
    print("✅ TRAINING COMPLETE")
    print("="*60)
    print(f"   Successful: {successful}")
    print(f"   Failed: {failed}")
    print(f"   Skipped (already trained): {skipped}")
    print(f"   Total time: {elapsed_mins:.1f} minutes")
    print(f"   Models saved to: models/ml_ema/")
    print("="*60)
    
    print("\n📋 Next steps:")
    print("1. Review model accuracy in logs")
    print("2. Keep DRY_RUN=true to test in paper trading")
    print("3. Monitor for 24-48 hours")
    print("4. Go live: Set DRY_RUN=false")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Training cancelled by user")
        sys.exit(1)
