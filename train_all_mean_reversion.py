#!/usr/bin/env python3
"""Train mean reversion models for all USDT pairs"""
import subprocess
import sys
from binance.client import Client
import os

# Load API keys
os.chdir('/Users/smithd/Desktop/binance-trading-bot')
from dotenv import load_dotenv
load_dotenv()

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

# Get all USDT pairs
print("Fetching pairs from Binance...")
info = client.get_exchange_info()
pairs = [s['symbol'] for s in info['symbols'] 
         if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'
         and s['symbol'] not in ['USDCUSDT', 'TUSDUSDT', 'BUSDUSDT', 'FDUSDUSDT', 'USDEUSDT']]

pairs.sort()
total = len(pairs)
print(f"\nTraining {total} pairs on 1h timeframe...")
print("=" * 60)

success = 0
failed = 0

for i, symbol in enumerate(pairs, 1):
    print(f"[{i}/{total}] {symbol}...", end=' ', flush=True)
    
    cmd = [
        'docker-compose', 'exec', '-T', 'web-ui',
        'python', '-m', 'src.utils.train_mean_reversion',
        '--symbol', symbol,
        '--interval', '1h',
        '--lookback-days', '180'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0:
            success += 1
            print("✓")
        else:
            failed += 1
            print("✗")
    except subprocess.TimeoutExpired:
        failed += 1
        print("✗ (timeout)")
    except Exception as e:
        failed += 1
        print(f"✗ ({e})")

print("\n" + "=" * 60)
print(f"Complete! ✓ {success} | ✗ {failed}")
print("\nRestarting bot...")

# Restart bot
subprocess.run(['curl', '-s', '-X', 'POST', 'http://localhost:5000/api/stop'], capture_output=True)
subprocess.run(['sleep', '2'])
subprocess.run(['docker-compose', 'restart', 'web-ui'], capture_output=True)
subprocess.run(['sleep', '5'])
subprocess.run(['curl', '-s', '-X', 'POST', 'http://localhost:5000/api/start'], capture_output=True)

print("✅ Bot restarted with all new models!")
