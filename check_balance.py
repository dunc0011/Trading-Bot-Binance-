#!/usr/bin/env python3
"""Quick balance checker"""
from binance.client import Client
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
trading_mode = os.getenv('TRADING_MODE', 'testnet')

# Connect to correct endpoint
if trading_mode == "testnet":
    client = Client(api_key, api_secret, testnet=True)
    print("🧪 Connected to TESTNET")
else:
    client = Client(api_key, api_secret)
    print("💰 Connected to LIVE")

# Get account info
account = client.get_account()

# Show all non-zero balances
print("\n📊 All non-zero balances:")
for asset in account['balances']:
    free = float(asset['free'])
    locked = float(asset['locked'])
    total = free + locked
    if total > 0:
        print(f"  {asset['asset']}: {total:.8f} (free: {free:.8f}, locked: {locked:.8f})")

# Focus on USDT
usdt = [b for b in account['balances'] if b['asset'] == 'USDT'][0]
print(f"\n💵 USDT Balance:")
print(f"  Free: ${float(usdt['free']):.2f}")
print(f"  Locked: ${float(usdt.get('locked', 0)):.2f}")
print(f"  Total: ${float(usdt['free']) + float(usdt.get('locked', 0)):.2f}")
