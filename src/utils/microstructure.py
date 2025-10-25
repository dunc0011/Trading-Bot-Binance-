"""
Market Microstructure Analysis
Analyzes order book and trade flow to improve entry timing
"""
import logging
import numpy as np
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class MicrostructureAnalyzer:
    """Analyze order book and trade flow for smart entries."""
    
    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger(__name__)
    
    def get_order_book_imbalance(self, symbol: str, depth: int = 10) -> float:
        """
        Calculate order book imbalance (buy pressure vs sell pressure).
        
        Returns:
            float: Imbalance ratio (-1 to 1)
                   > 0 = more buy pressure (good for entry)
                   < 0 = more sell pressure (avoid entry)
        """
        try:
            depth_data = self.client.get_order_book(symbol=symbol, limit=depth)
            
            # Calculate bid and ask volumes
            bid_volume = sum(float(bid[1]) for bid in depth_data['bids'])
            ask_volume = sum(float(ask[1]) for ask in depth_data['asks'])
            
            total_volume = bid_volume + ask_volume
            if total_volume == 0:
                return 0
            
            # Imbalance: positive = more bids, negative = more asks
            imbalance = (bid_volume - ask_volume) / total_volume
            
            self.logger.debug(f"{symbol} order book imbalance: {imbalance:.3f}")
            return imbalance
        
        except Exception as e:
            self.logger.error(f"Error calculating order book imbalance: {e}")
            return 0
    
    def get_spread_info(self, symbol: str) -> Dict[str, float]:
        """Get bid-ask spread information."""
        try:
            ticker = self.client.get_orderbook_ticker(symbol=symbol)
            
            bid = float(ticker['bidPrice'])
            ask = float(ticker['askPrice'])
            mid = (bid + ask) / 2
            
            spread = ask - bid
            spread_pct = (spread / mid) * 100
            
            return {
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'spread': spread,
                'spread_pct': spread_pct
            }
        
        except Exception as e:
            self.logger.error(f"Error getting spread: {e}")
            return {'spread_pct': 999}
    
    def should_enter(self, symbol: str) -> Dict[str, any]:
        """
        Determine if current market microstructure favors entry.
        
        Returns:
            dict with 'allowed' (bool) and 'reason' (str)
        """
        # Check order book imbalance
        imbalance = self.get_order_book_imbalance(symbol)
        
        # Check spread
        spread_info = self.get_spread_info(symbol)
        spread_pct = spread_info['spread_pct']
        
        # Decision logic
        reasons = []
        
        # Require positive buy pressure
        if imbalance < -0.2:  # Heavy sell pressure
            return {
                'allowed': False,
                'reason': f'Heavy sell pressure (imbalance: {imbalance:.2f})',
                'imbalance': imbalance,
                'spread_pct': spread_pct
            }
        
        # Avoid wide spreads (low liquidity)
        if spread_pct > 0.15:  # Spread > 0.15%
            return {
                'allowed': False,
                'reason': f'Wide spread ({spread_pct:.3f}%)',
                'imbalance': imbalance,
                'spread_pct': spread_pct
            }
        
        # Prefer strong buy pressure
        if imbalance > 0.1:
            reasons.append(f'Good buy pressure ({imbalance:.2f})')
        
        # Good liquidity
        if spread_pct < 0.05:
            reasons.append(f'Tight spread ({spread_pct:.3f}%)')
        
        return {
            'allowed': True,
            'reason': ', '.join(reasons) if reasons else 'Neutral conditions',
            'imbalance': imbalance,
            'spread_pct': spread_pct,
            'optimal_entry_price': spread_info['bid']  # Enter at bid to avoid spread
        }
