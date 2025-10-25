#!/usr/bin/env python3
"""
Binance API Connection Test
Tests if your API keys are working correctly
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
from config.config import Config

def test_api_connection():
    """Test Binance API connection and permissions"""
    
    print("=" * 60)
    print("BINANCE API CONNECTION TEST")
    print("=" * 60)
    
    # Load config
    load_dotenv()
    config = Config()
    
    print(f"\n📋 Configuration:")
    print(f"   Trading Mode: {config.trading_mode}")
    print(f"   Symbol: {config.symbol}")
    print(f"   Timeframe: {config.timeframe}")
    print(f"   Dry Run: {config.dry_run}")
    print(f"   Strategy: {config.strategy}")
    
    # Check if API keys are set
    if not config.api_key or not config.api_secret:
        print("\n❌ ERROR: API keys not found in .env file!")
        print("\nPlease add to .env:")
        print("   BINANCE_API_KEY=your_key_here")
        print("   BINANCE_API_SECRET=your_secret_here")
        return False
    
    print(f"\n🔑 API Key: {config.api_key[:8]}..." + "*" * 20)
    
    # Initialize client
    try:
        if config.trading_mode == "testnet":
            client = Client(config.api_key, config.api_secret, testnet=True)
            print("\n🧪 Using TESTNET")
        else:
            client = Client(config.api_key, config.api_secret)
            print("\n💰 Using LIVE TRADING")
    except Exception as e:
        print(f"\n❌ Failed to create client: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("RUNNING TESTS...")
    print("=" * 60)
    
    # Test 1: Server connectivity
    print("\n1️⃣  Testing server connectivity...")
    try:
        server_time = client.get_server_time()
        print(f"   ✅ Server time: {server_time['serverTime']}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 2: API permissions
    print("\n2️⃣  Testing API permissions...")
    try:
        account = client.get_account()
        print(f"   ✅ Account type: {account['accountType']}")
        print(f"   ✅ Can trade: {account['canTrade']}")
        print(f"   ✅ Can withdraw: {account['canWithdraw']}")
        print(f"   ✅ Can deposit: {account['canDeposit']}")
    except BinanceAPIException as e:
        print(f"   ❌ API Error [{e.code}]: {e.message}")
        if e.code == -2015:
            print("\n   ⚠️  HINT: Check your API key permissions on Binance")
            print("      Required: 'Enable Reading' and 'Enable Spot Trading'")
        return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 3: Account balances
    print("\n3️⃣  Checking account balances...")
    try:
        balances = client.get_account()['balances']
        non_zero = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        
        if non_zero:
            print(f"   ✅ Found {len(non_zero)} assets with balance:")
            for balance in non_zero[:10]:  # Show first 10
                asset = balance['asset']
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked
                print(f"      {asset}: {total:.8f} (free: {free:.8f})")
        else:
            print("   ⚠️  No balances found (this is normal for new accounts)")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 4: Market data access
    print("\n4️⃣  Testing market data access...")
    try:
        ticker = client.get_symbol_ticker(symbol=config.symbol)
        print(f"   ✅ Current {config.symbol} price: ${float(ticker['price']):,.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 5: Klines data (for ML)
    print("\n5️⃣  Testing historical data access...")
    try:
        klines = client.get_klines(
            symbol=config.symbol,
            interval=config.timeframe,
            limit=10
        )
        print(f"   ✅ Fetched {len(klines)} candles for {config.symbol} ({config.timeframe})")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 6: Exchange info
    print("\n6️⃣  Testing exchange info...")
    try:
        exchange_info = client.get_exchange_info()
        symbols = exchange_info['symbols']
        usdt_pairs = [s for s in symbols if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
        print(f"   ✅ Found {len(usdt_pairs)} active USDT trading pairs")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test 7: Order test (doesn't place real order)
    print("\n7️⃣  Testing order endpoint (test mode)...")
    try:
        # This tests the order endpoint without actually placing an order
        result = client.create_test_order(
            symbol=config.symbol,
            side='BUY',
            type='MARKET',
            quantity=0.001
        )
        print(f"   ✅ Order test successful (no real order placed)")
    except BinanceAPIException as e:
        if e.code == -1013:
            print(f"   ⚠️  Order test failed (but API works): {e.message}")
            print(f"      This is normal - just means we can't trade with test parameters")
        else:
            print(f"   ❌ API Error [{e.code}]: {e.message}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    print("\n" + "=" * 60)
    print("✅ ALL CRITICAL TESTS PASSED!")
    print("=" * 60)
    print("\n🎉 Your Binance API is working correctly!")
    print("\nNext steps:")
    print("   1. Train an ML model: docker-compose exec web-ui python -m src.utils.train_ml_model")
    print("   2. Open dashboard: http://localhost:5000")
    print("   3. Start trading (dry-run recommended first)")
    print("\n")
    
    return True

if __name__ == "__main__":
    success = test_api_connection()
    sys.exit(0 if success else 1)
