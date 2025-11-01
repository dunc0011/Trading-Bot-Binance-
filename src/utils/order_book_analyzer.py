"""
Order Book Depth Analyzer
Analyzes order book liquidity to detect thin markets and pump-and-dump schemes
"""
import logging
from typing import Dict, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException


logger = logging.getLogger(__name__)


class OrderBookAnalyzer:
    """Analyzes order book depth for liquidity validation"""
    
    def __init__(self, client: Client):
        self.client = client
        self.logger = logging.getLogger(__name__)
    
    def get_order_book(self, symbol: str, limit: int = 500) -> Optional[Dict]:
        """
        Fetch order book snapshot from Binance
        
        Args:
            symbol: Trading pair (e.g., 'DASHUSDT')
            limit: Number of levels to fetch (5, 10, 20, 50, 100, 500, 1000, 5000)
        
        Returns:
            Dict with 'bids' and 'asks' lists, or None on error
        """
        try:
            depth = self.client.get_order_book(symbol=symbol, limit=limit)
            return depth
        except BinanceAPIException as e:
            self.logger.error(f"Failed to fetch order book for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching order book for {symbol}: {e}")
            return None
    
    def compute_depth_within_pct(self, symbol: str, pct: float = 0.01, limit: int = 500) -> Dict:
        """
        Calculate liquidity depth within a percentage range of mid price
        
        Args:
            symbol: Trading pair
            pct: Percentage range (0.01 = 1%)
            limit: Order book depth to fetch
        
        Returns:
            Dict with:
                - bid_usdt: Total USDT value of bids within range
                - ask_usdt: Total USDT value of asks within range
                - mid: Mid price
                - is_liquid: Boolean indicating if both sides meet threshold
        """
        depth = self.get_order_book(symbol, limit=limit)
        
        if not depth or not depth.get('bids') or not depth.get('asks'):
            return {
                'bid_usdt': 0,
                'ask_usdt': 0,
                'mid': 0,
                'is_liquid': False,
                'error': 'Failed to fetch order book'
            }
        
        try:
            # Calculate mid price
            best_bid = float(depth['bids'][0][0])
            best_ask = float(depth['asks'][0][0])
            mid = (best_bid + best_ask) / 2
            
            # Calculate depth thresholds
            bid_threshold = mid * (1 - pct)
            ask_threshold = mid * (1 + pct)
            
            # Aggregate bid depth (USDT value)
            bid_usdt = sum(
                float(price) * float(qty)
                for price, qty in depth['bids']
                if float(price) >= bid_threshold
            )
            
            # Aggregate ask depth (USDT value)
            ask_usdt = sum(
                float(price) * float(qty)
                for price, qty in depth['asks']
                if float(price) <= ask_threshold
            )
            
            return {
                'bid_usdt': bid_usdt,
                'ask_usdt': ask_usdt,
                'mid': mid,
                'bid_threshold': bid_threshold,
                'ask_threshold': ask_threshold,
                'is_liquid': False  # Will be set by is_liquid()
            }
        
        except Exception as e:
            self.logger.error(f"Error calculating depth for {symbol}: {e}")
            return {
                'bid_usdt': 0,
                'ask_usdt': 0,
                'mid': 0,
                'is_liquid': False,
                'error': str(e)
            }
    
    def is_liquid(self, symbol: str, min_each_side: float = 50000, pct: float = 0.01) -> tuple[bool, Dict]:
        """
        Check if a symbol has sufficient liquidity on both sides
        
        Args:
            symbol: Trading pair
            min_each_side: Minimum USDT depth required on each side (default $50k)
            pct: Percentage range to check (default 1%)
        
        Returns:
            Tuple of (is_liquid: bool, depth_info: Dict)
        """
        depth_info = self.compute_depth_within_pct(symbol, pct=pct)
        
        is_liquid = (
            depth_info['bid_usdt'] >= min_each_side and
            depth_info['ask_usdt'] >= min_each_side and
            'error' not in depth_info
        )
        
        depth_info['is_liquid'] = is_liquid
        depth_info['min_threshold'] = min_each_side
        
        if is_liquid:
            self.logger.debug(
                f"{symbol} is liquid: ${depth_info['bid_usdt']:,.0f} bid, "
                f"${depth_info['ask_usdt']:,.0f} ask within {pct*100}%"
            )
        else:
            self.logger.warning(
                f"{symbol} is NOT liquid: ${depth_info['bid_usdt']:,.0f} bid, "
                f"${depth_info['ask_usdt']:,.0f} ask (need ${min_each_side:,.0f} each)"
            )
        
        return is_liquid, depth_info
