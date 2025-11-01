"""
Check Binance account fee tier and BNB balance
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from binance.client import Client
from config.config import Config

def check_account_fees():
    """Check trading fee tier and BNB balance."""
    config = Config()
    testnet = config.trading_mode == 'testnet'
    client = Client(config.api_key, config.api_secret, testnet=testnet)
    
    print("\n" + "="*60)
    print("BINANCE ACCOUNT FEE ANALYSIS")
    print("="*60)
    
    # Get account info
    account = client.get_account()
    
    # Check maker/taker fees
    print(f"\n📊 Trading Fees:")
    print(f"  Maker Fee: {float(account.get('makerCommission', 10)) / 100:.2f}%")
    print(f"  Taker Fee: {float(account.get('takerCommission', 10)) / 100:.2f}%")
    print(f"  Buyer Fee: {float(account.get('buyerCommission', 0)) / 100:.2f}%")
    print(f"  Seller Fee: {float(account.get('sellerCommission', 0)) / 100:.2f}%")
    
    # Check BNB balance
    bnb_balance = client.get_asset_balance(asset='BNB')
    if bnb_balance:
        bnb_free = float(bnb_balance.get('free', 0))
        bnb_locked = float(bnb_balance.get('locked', 0))
        bnb_total = bnb_free + bnb_locked
        
        # Get BNB price in USDT
        bnb_price_ticker = client.get_symbol_ticker(symbol='BNBUSDT')
        bnb_price = float(bnb_price_ticker['price'])
        bnb_value_usdt = bnb_total * bnb_price
        
        print(f"\n💰 BNB Balance:")
        print(f"  Free: {bnb_free:.8f} BNB (${bnb_free * bnb_price:.2f})")
        print(f"  Locked: {bnb_locked:.8f} BNB (${bnb_locked * bnb_price:.2f})")
        print(f"  Total: {bnb_total:.8f} BNB (${bnb_value_usdt:.2f})")
        print(f"  BNB Price: ${bnb_price:.2f}")
        
        if bnb_total < 0.01:
            print("\n⚠️  WARNING: Low BNB balance! Consider adding BNB for fee discounts.")
            print("   Binance gives 25% fee discount when paying fees with BNB.")
    else:
        print("\n⚠️  No BNB balance found!")
        print("   Consider buying BNB to save 25% on trading fees.")
    
    # Check if BNB fee payment is enabled (check recent trades)
    print(f"\n🔍 Recent Trade Fees:")
    try:
        # Get recent trades for a common pair
        trades = client.get_my_trades(symbol='BTCUSDT', limit=5)
        if trades:
            for trade in trades[:3]:  # Show last 3
                commission = float(trade.get('commission', 0))
                commission_asset = trade.get('commissionAsset', 'UNKNOWN')
                qty = float(trade.get('qty', 0))
                price = float(trade.get('price', 0))
                notional = qty * price
                fee_pct = (commission * price / notional * 100) if commission_asset != 'USDT' else (commission / notional * 100)
                
                print(f"  Trade {trade['id']}: {commission:.8f} {commission_asset} on ${notional:.2f} ({fee_pct:.3f}%)")
        else:
            print("  No recent BTCUSDT trades found")
    except Exception as e:
        print(f"  Could not fetch recent trades: {e}")
    
    # Check API trading status
    api_perms = account.get('canTrade', False)
    print(f"\n🔑 API Status:")
    print(f"  Trading Enabled: {api_perms}")
    
    print("\n" + "="*60)
    print("\n💡 To enable BNB fee discount:")
    print("   1. Go to Binance.com → Profile → Dashboard")
    print("   2. Find 'Using BNB to pay for fees' and enable it")
    print("   3. Keep at least $5-10 worth of BNB in your account")
    print("   4. This gives you 25% discount on all trading fees")
    print("="*60 + "\n")

if __name__ == '__main__':
    check_account_fees()
