"""
Volume Profile Analysis
Identifies high-volume price zones for better entry/exit timing
"""
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class VolumeProfileAnalyzer:
    """Analyze volume profile to find support/resistance levels"""
    
    def __init__(self, num_bins: int = 20):
        self.num_bins = num_bins
    
    def calculate_volume_profile(self, klines: list) -> dict:
        """
        Calculate volume profile from kline data
        
        Args:
            klines: List of kline data from Binance
            
        Returns:
            dict with support/resistance levels
        """
        try:
            # Convert to DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            df['close'] = pd.to_numeric(df['close'])
            df['volume'] = pd.to_numeric(df['volume'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            
            # Calculate price range
            price_min = df['low'].min()
            price_max = df['high'].max()
            
            # Create price bins
            bins = np.linspace(price_min, price_max, self.num_bins)
            volume_by_price = np.zeros(self.num_bins - 1)
            
            # Distribute volume across price levels
            for _, row in df.iterrows():
                # Assume volume distributed evenly across high-low range
                low_idx = np.digitize(row['low'], bins) - 1
                high_idx = np.digitize(row['high'], bins) - 1
                
                # Add volume to all bins in range
                for i in range(max(0, low_idx), min(len(volume_by_price), high_idx + 1)):
                    volume_by_price[i] += row['volume'] / max(1, high_idx - low_idx + 1)
            
            # Find high volume nodes (support/resistance)
            bin_centers = (bins[:-1] + bins[1:]) / 2
            
            # Get top 3 high-volume levels
            top_indices = np.argsort(volume_by_price)[-3:]
            high_volume_levels = bin_centers[top_indices]
            
            # Current price
            current_price = df['close'].iloc[-1]
            
            # Classify as support (below price) or resistance (above price)
            support_levels = [level for level in high_volume_levels if level < current_price]
            resistance_levels = [level for level in high_volume_levels if level >= current_price]
            
            # Find closest levels
            closest_support = max(support_levels) if support_levels else price_min
            closest_resistance = min(resistance_levels) if resistance_levels else price_max
            
            # Calculate distance from current price
            support_distance_pct = abs((current_price - closest_support) / current_price) * 100
            resistance_distance_pct = abs((closest_resistance - current_price) / current_price) * 100
            
            return {
                'current_price': current_price,
                'closest_support': closest_support,
                'closest_resistance': closest_resistance,
                'support_distance_pct': support_distance_pct,
                'resistance_distance_pct': resistance_distance_pct,
                'all_support': sorted(support_levels, reverse=True),
                'all_resistance': sorted(resistance_levels),
                'at_support': support_distance_pct < 0.5,  # Within 0.5% of support
                'at_resistance': resistance_distance_pct < 0.5,  # Within 0.5% of resistance
            }
        
        except Exception as e:
            logger.error(f"Volume profile calculation failed: {e}")
            return {}
    
    def should_enter(self, volume_profile: dict) -> bool:
        """
        Check if current price is at a good entry point (near support)
        
        Args:
            volume_profile: Output from calculate_volume_profile
            
        Returns:
            True if good entry point
        """
        if not volume_profile:
            return True  # Allow if unable to calculate
        
        # Good entry: At or near support (bounce opportunity)
        if volume_profile.get('at_support'):
            return True
        
        # Decent entry: Not at resistance and support not too far
        if not volume_profile.get('at_resistance') and volume_profile.get('support_distance_pct', 999) < 2.0:
            return True
        
        # Bad entry: At resistance (likely to reject)
        return False
