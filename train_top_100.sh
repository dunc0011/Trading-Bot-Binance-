#!/bin/bash
# Train ML models for top 100 USDT pairs by 24h volume

echo "🚀 Training ML EMA models for top 100 pairs by volume..."
echo ""

# Fetch top 100 pairs dynamically and train them
docker-compose exec -T web-ui python3 << 'PYTHON_SCRIPT'
from binance.client import Client
import os
import subprocess
import sys

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

print("📊 Fetching top 100 USDT pairs by 24h volume...")
tickers = client.get_ticker()
usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]

# Sort by 24h volume (quote volume in USDT)
usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)

# Get top 100
top_100 = usdt_pairs[:100]

print(f"\n✅ Found {len(top_100)} pairs to train")
print(f"\nTop 10 by volume:")
for i, ticker in enumerate(top_100[:10], 1):
    symbol = ticker['symbol']
    volume_m = float(ticker['quoteVolume']) / 1_000_000
    print(f"  {i:2d}. {symbol:15s} ${volume_m:8.1f}M")

print(f"\n🎯 Training {len(top_100)} pairs...")
print("=" * 70)

succeeded = []
failed = []
skipped = []

for i, ticker in enumerate(top_100, 1):
    symbol = ticker['symbol']
    volume_m = float(ticker['quoteVolume']) / 1_000_000
    
    # Skip stablecoins (low volatility)
    if symbol in ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'USDEUSDT', 'DAIUSDT']:
        print(f"[{i}/100] ⏭️  {symbol:15s} - Skipped (stablecoin)")
        skipped.append(symbol)
        continue
    
    print(f"[{i}/100] Training {symbol:15s} (${volume_m:6.1f}M volume)...", end=' ')
    
    try:
        result = subprocess.run(
            ['python', '-m', 'src.utils.train_ml_model',
             '--symbol', symbol,
             '--interval', '1h',
             '--lookback-days', '90',
             '--log-level', 'WARNING'],
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout
        )
        
        if result.returncode == 0:
            print("✅")
            succeeded.append(symbol)
        else:
            print(f"❌ ({result.stderr[:50]})")
            failed.append(symbol)
    
    except subprocess.TimeoutExpired:
        print("⏱️  timeout")
        failed.append(symbol)
    except Exception as e:
        print(f"❌ {str(e)[:50]}")
        failed.append(symbol)

print("\n" + "=" * 70)
print(f"\n📊 Training Summary:")
print(f"  ✅ Succeeded: {len(succeeded)}/100")
print(f"  ❌ Failed: {len(failed)}/100")
print(f"  ⏭️  Skipped: {len(skipped)}/100 (stablecoins)")
print(f"  📈 Total tradeable: {len(succeeded)}")

if failed and len(failed) <= 10:
    print(f"\n❌ Failed pairs: {', '.join(failed)}")
elif failed:
    print(f"\n❌ Failed: {', '.join(failed[:10])} ...and {len(failed)-10} more")

# Save list of successfully trained pairs
with open('/app/trained_pairs_top100.txt', 'w') as f:
    f.write(','.join(succeeded))

print(f"\n✅ Saved trained pairs to: trained_pairs_top100.txt")
print(f"🎉 Training complete! You can now trade {len(succeeded)} pairs.")
PYTHON_SCRIPT

echo ""
echo "✅ Done! Update .env with the new pairs list or restart bot."
