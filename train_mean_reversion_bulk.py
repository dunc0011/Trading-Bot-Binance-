#!/usr/bin/env python3
"""
Train mean reversion models for all top USDT pairs
"""
import sys
sys.path.insert(0, '/app')
import subprocess
import time
from binance.client import Client
from config.config import Config

# Get top pairs by volume
config = Config()
if config.trading_mode == "testnet":
    client = Client(config.api_key, config.api_secret, testnet=True)
else:
    client = Client(config.api_key, config.api_secret)

print("🔍 Fetching top USDT pairs...")
tickers = client.get_ticker()

usdt_pairs = []
for ticker in tickers:
    symbol = ticker['symbol']
    if symbol.endswith('USDT') and symbol not in ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT']:
        try:
            volume = float(ticker['quoteVolume'])
            if volume >= 5_000_000:  # $5M+ volume
                usdt_pairs.append((symbol, volume))
        except:
            continue

usdt_pairs.sort(key=lambda x: x[1], reverse=True)
pairs = [p[0] for p in usdt_pairs]

print(f"✅ Found {len(pairs)} pairs with $5M+ volume")
print(f"Training with 15m timeframe, 90 days lookback\n")

successful = 0
failed = 0

for i, symbol in enumerate(pairs, 1):
    print(f"\n[{i}/{len(pairs)}] Training {symbol}...")
    
    cmd = [
        'python', '-m', 'src.utils.train_mean_reversion',
        '--symbol', symbol,
        '--interval', '15m',
        '--lookback-days', '90'
    ]
    
    try:
        result = subprocess.run(cmd, cwd='/app', capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {symbol} trained")
            successful += 1
        else:
            print(f"❌ {symbol} failed")
            failed += 1
    except Exception as e:
        print(f"❌ {symbol} error: {e}")
        failed += 1
    
    time.sleep(1)  # Rate limit protection

print(f"\n{'='*60}")
print(f"✅ COMPLETE: {successful} successful, {failed} failed")
print(f"{'='*60}")
