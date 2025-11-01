"""
Momentum Risk Manager
Specialized risk management for momentum/breakout trades with:
- Conservative position sizing (2-3% of portfolio)
- Fixed SL/TP (7% SL, 14% TP default)
- Trailing stops activated at +7%
- Time-to-live (TTL) exits for stalling positions
- Reversal detection for early exits
"""
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class MomentumRiskManager:
    """
    Risk management for momentum trades with strict controls
    """
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Position sizing
        self.position_size_pct = float(getattr(config, 'momentum_position_size_pct', 2.0)) / 100  # 2% default
        self.max_position_size = getattr(config, 'max_position_size', None)  # Cap if set
        
        # Stop loss / Take profit
        self.stop_loss_pct = float(getattr(config, 'momentum_stop_loss_pct', 7.0)) / 100  # 7% default
        self.take_profit_pct = float(getattr(config, 'momentum_take_profit_pct', 14.0)) / 100  # 14% default
        
        # Trailing stop
        self.trailing_activation_pct = 0.07  # Activate trailing at +7%
        self.trailing_distance_pct = 0.5  # Trail at 50% of peak gain
        
        # Position limits
        self.max_momentum_positions = int(getattr(config, 'momentum_max_positions', 3))
        self.max_total_positions = 10  # Block momentum if total > 10
        
        # Time-to-live (TTL) for stalling positions
        self.ttl_hours = 4  # Force exit after 4 hours
        self.ttl_min_gain_pct = 0.03  # Require +3% to extend TTL
        
        # Reversal detection thresholds
        self.reversal_rsi_delta = -5  # RSI lower high by 5+ points
        self.reversal_volume_threshold = 0.8  # Volume below 80% of SMA
        self.reversal_candle_count = 3  # 3 candles of weak volume
        
        self.logger.info(
            f"MomentumRiskManager initialized: {self.position_size_pct*100:.1f}% sizing, "
            f"{self.stop_loss_pct*100:.0f}% SL, {self.take_profit_pct*100:.0f}% TP"
        )
    
    def size_position(self, price: float, balance_usdt: float) -> float:
        """
        Calculate position size in USDT for a momentum trade
        
        Args:
            price: Entry price
            balance_usdt: Available USDT balance
        
        Returns:
            Position size in USDT
        """
        # Calculate base size as percentage of balance
        position_usdt = balance_usdt * self.position_size_pct
        
        # Apply max cap if configured
        if self.max_position_size is not None:
            position_usdt = min(position_usdt, self.max_position_size)
        
        # Ensure minimum notional (Binance requires $10 minimum typically)
        min_notional = 10.0
        if position_usdt < min_notional:
            self.logger.warning(f"Position size ${position_usdt:.2f} below min notional ${min_notional}")
            return 0.0
        
        self.logger.debug(f"Momentum position sized: ${position_usdt:.2f} ({self.position_size_pct*100:.1f}% of ${balance_usdt:.0f})")
        return position_usdt
    
    def stops_targets(self, entry_price: float) -> tuple[float, float]:
        """
        Calculate stop loss and take profit levels
        
        Args:
            entry_price: Entry price
        
        Returns:
            Tuple of (stop_loss_price, take_profit_price)
        """
        stop_loss = entry_price * (1 - self.stop_loss_pct)
        take_profit = entry_price * (1 + self.take_profit_pct)
        
        self.logger.debug(
            f"Stops/Targets for entry ${entry_price:.4f}: "
            f"SL ${stop_loss:.4f} (-{self.stop_loss_pct*100:.0f}%), "
            f"TP ${take_profit:.4f} (+{self.take_profit_pct*100:.0f}%)"
        )
        
        return stop_loss, take_profit
    
    def update_trailing(self, position: Dict, current_price: float) -> Optional[float]:
        """
        Update trailing stop for a momentum position
        
        Args:
            position: Position dict with 'entry_price', 'peak_price' (optional), 'stop_loss'
            current_price: Current market price
        
        Returns:
            New stop loss price if trailing should be updated, None otherwise
        """
        entry_price = position['entry_price']
        current_gain_pct = (current_price - entry_price) / entry_price
        
        # Only activate trailing if we've hit the activation threshold
        if current_gain_pct < self.trailing_activation_pct:
            return None
        
        # Track peak price
        peak_price = position.get('peak_price', entry_price)
        if current_price > peak_price:
            peak_price = current_price
            position['peak_price'] = peak_price  # Update in place
        
        # Calculate peak gain from entry
        peak_gain_pct = (peak_price - entry_price) / entry_price
        
        # Trailing stop: entry + (peak_gain - activation_threshold) * trailing_distance
        # This locks in 50% of gains above the +7% activation level
        protected_gain = self.trailing_activation_pct + (peak_gain_pct - self.trailing_activation_pct) * self.trailing_distance_pct
        new_stop = entry_price * (1 + protected_gain)
        
        # Only update if new stop is higher than current stop
        current_stop = position.get('stop_loss', entry_price * (1 - self.stop_loss_pct))
        if new_stop > current_stop:
            self.logger.info(
                f"📈 Trailing stop updated: ${current_stop:.4f} → ${new_stop:.4f} "
                f"(peak ${peak_price:.4f}, gain {peak_gain_pct*100:.1f}%)"
            )
            return new_stop
        
        return None
    
    def should_exit_ttl(self, position: Dict, indicators: Dict) -> bool:
        """
        Check if position should exit due to time-to-live (TTL) expiry
        
        Args:
            position: Position dict with 'entry_time', 'entry_price'
            indicators: Current market indicators with 'adx', 'volume_ratio'
        
        Returns:
            True if position should exit due to TTL, False otherwise
        """
        entry_time = position.get('entry_time')
        if not entry_time:
            return False
        
        # Parse entry time
        if isinstance(entry_time, str):
            entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
        
        time_held = datetime.now() - entry_time
        
        # Check if TTL expired
        if time_held < timedelta(hours=self.ttl_hours):
            return False
        
        # TTL expired - check if position has made sufficient progress
        current_price = indicators.get('current_price', position['entry_price'])
        gain_pct = (current_price - position['entry_price']) / position['entry_price']
        
        if gain_pct >= self.ttl_min_gain_pct:
            # Position is up +3% or more, give it more time
            self.logger.debug(f"TTL: Position up {gain_pct*100:.1f}%, extending time")
            return False
        
        # Check if momentum is weakening
        adx = indicators.get('adx', 0)
        volume_ratio = indicators.get('volume_ratio', 1.0)
        
        if adx < 25 or volume_ratio < 1.0:
            self.logger.warning(
                f"⏰ TTL EXIT: Position stalling after {time_held.total_seconds()/3600:.1f}h "
                f"(gain {gain_pct*100:.1f}%, ADX {adx:.0f}, vol ratio {volume_ratio:.2f}x)"
            )
            return True
        
        return False
    
    def should_exit_reversal(self, indicators: Dict, lookback_indicators: list[Dict] = None) -> bool:
        """
        Detect if momentum is reversing (bearish divergence)
        
        Args:
            indicators: Current indicators with 'rsi', 'price'
            lookback_indicators: List of recent indicator dicts (last 3-5 candles)
        
        Returns:
            True if reversal detected, False otherwise
        """
        if not lookback_indicators or len(lookback_indicators) < 3:
            return False
        
        try:
            # Get current RSI and price
            current_rsi = indicators.get('rsi', 50)
            current_price = indicators.get('current_price', 0)
            
            # Get previous peak RSI and price
            prev_rsi_peak = max(ind.get('rsi', 50) for ind in lookback_indicators[-3:])
            prev_price_peak = max(ind.get('current_price', 0) for ind in lookback_indicators[-3:])
            
            # Check for bearish divergence: price making higher high but RSI making lower high
            price_higher_high = current_price > prev_price_peak
            rsi_lower_high = current_rsi < (prev_rsi_peak + self.reversal_rsi_delta)
            
            if price_higher_high and rsi_lower_high:
                # Check volume confirmation (last 3 candles below average)
                weak_volume_count = sum(
                    1 for ind in lookback_indicators[-3:]
                    if ind.get('volume_ratio', 1.0) < self.reversal_volume_threshold
                )
                
                if weak_volume_count >= self.reversal_candle_count:
                    self.logger.warning(
                        f"🔄 REVERSAL DETECTED: Price ${current_price:.4f} (HH) but RSI {current_rsi:.0f} (LH), "
                        f"weak volume {weak_volume_count}/3 candles"
                    )
                    return True
        
        except Exception as e:
            self.logger.error(f"Error in reversal detection: {e}")
        
        return False
    
    def can_open_momentum_position(self, active_positions: Dict) -> tuple[bool, str]:
        """
        Check if we can open a new momentum position
        
        Args:
            active_positions: Dict of all active positions
        
        Returns:
            Tuple of (can_open: bool, reason: str)
        """
        # Count momentum positions
        momentum_count = sum(
            1 for pos in active_positions.values()
            if pos.get('strategy_type') == 'MOMENTUM'
        )
        
        if momentum_count >= self.max_momentum_positions:
            return False, f"Max momentum positions reached ({momentum_count}/{self.max_momentum_positions})"
        
        # Check total position limit
        total_positions = len(active_positions)
        if total_positions >= self.max_total_positions:
            return False, f"Total position limit reached ({total_positions}/{self.max_total_positions})"
        
        return True, "OK"
    
    def calculate_risk_level(self, atr_pct: float, liquidity_score: float, momentum_score: float) -> str:
        """
        Calculate risk level for a momentum trade
        
        Args:
            atr_pct: ATR as percentage of price
            liquidity_score: 0-1 liquidity score (1 = highly liquid)
            momentum_score: 0-10 momentum score
        
        Returns:
            Risk level: 'LOW', 'MEDIUM', or 'HIGH'
        """
        risk_points = 0
        
        # ATR risk (higher ATR = higher risk)
        if atr_pct > 4.0:
            risk_points += 3
        elif atr_pct > 3.0:
            risk_points += 2
        elif atr_pct > 2.0:
            risk_points += 1
        
        # Liquidity risk (lower liquidity = higher risk)
        if liquidity_score < 0.5:
            risk_points += 3
        elif liquidity_score < 0.75:
            risk_points += 2
        elif liquidity_score < 0.9:
            risk_points += 1
        
        # Momentum score (lower score = higher risk)
        if momentum_score < 6.0:
            risk_points += 2
        elif momentum_score < 7.5:
            risk_points += 1
        
        # Classify
        if risk_points <= 2:
            return 'LOW'
        elif risk_points <= 4:
            return 'MEDIUM'
        else:
            return 'HIGH'
