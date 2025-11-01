#!/bin/bash
# Train ML models for top tradeable pairs by 24h volume

echo "🚀 Training models for top tradeable USDT pairs..."
echo ""

# Run training inside Docker container
docker-compose exec -T web-ui python3 << 'PYTHON_SCRIPT'
from binance.client import Client
import os
import subprocess
import sys

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

print("📊 Fetching 24h ticker data for all USDT pairs...")

# Get all tickers with 24h volume
tickers = client.get_ticker()
usdt_tickers = [t for t in tickers if t['symbol'].endswith('USDT')]

# Sort by 24h volume (in USDT)
usdt_tickers.sort(key=lambda x: float(x['quoteVolume']), reverse=True)

# Get top 50 by volume
top_pairs = usdt_tickers[:50]

print(f"\n✅ Found {len(top_pairs)} pairs to train\n")
print("Top 10 pairs by 24h volume:")
for i, ticker in enumerate(top_pairs[:10], 1):
    symbol = ticker['symbol']
    volume = float(ticker['quoteVolume']) / 1_000_000  # Convert to millions
    print(f"  {i:2d}. {symbol:15s} - ${volume:,.1f}M volume")

print(f"\n🎯 Training models for top 50 pairs...")
print("=" * 60)

failed = []
succeeded = []

for i, ticker in enumerate(top_pairs, 1):
    symbol = ticker['symbol']
    print(f"\n[{i}/50] Training {symbol}...")
    
    try:
        # Run training command
        result = subprocess.run(
            ['python', '-m', 'src.utils.train_advanced_model',
             '--symbol', symbol,
             '--interval', '5m',
             '--lookback-days', '30'],  # 30 days for faster training
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout per pair
        )
        
        if result.returncode == 0:
            print(f"  ✅ {symbol} trained successfully")
            succeeded.append(symbol)
        else:
            print(f"  ❌ {symbol} failed: {result.stderr[:100]}")
            failed.append(symbol)
    
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  {symbol} timed out (>5min)")
        failed.append(symbol)
    except Exception as e:
        print(f"  ❌ {symbol} error: {str(e)[:100]}")
        failed.append(symbol)

print("\n" + "=" * 60)
print(f"\n📊 Training Summary:")
print(f"  ✅ Succeeded: {len(succeeded)}")
print(f"  ❌ Failed: {len(failed)}")

if failed:
    print(f"\n❌ Failed pairs: {', '.join(failed[:10])}")
    if len(failed) > 10:
        print(f"   ...and {len(failed) - 10} more")

print(f"\n🎉 Training complete!")
PYTHON_SCRIPT

echo ""
echo "✅ Done! Restart the bot to load new models."
