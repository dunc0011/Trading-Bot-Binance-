"""
Risk Management Module
"""
import logging


class RiskManager:
    """Manages risk and position sizing."""
    
    MIN_SAFE_FALLBACK_USDT = 10.0  # Fallback when balance API fails
    
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.logger = logging.getLogger(__name__)
        
        self.stop_loss_pct = config.stop_loss_percentage / 100
        self.take_profit_pct = config.take_profit_percentage / 100
    
    def check_risk(self, signal):
        """
        Evaluate if a trading signal meets risk criteria.
        
        Args:
            signal: Trading signal dictionary
            
        Returns:
            bool: True if signal passes risk checks
        """
        # Basic risk checks
        if signal['action'] not in ['BUY', 'SELL']:
            self.logger.warning(f"Invalid signal action: {signal['action']}")
            return False
        
        # Check if price is valid
        if signal['price'] <= 0:
            self.logger.warning("Invalid price in signal")
            return False
        
        # Add more sophisticated risk checks here
        # - Portfolio exposure
        # - Drawdown limits
        # - Volatility checks
        # - Correlation checks
        
        return True
    
    def get_free_usdt(self):
        """Fetch free USDT balance from Binance."""
        try:
            bal = self.client.get_asset_balance(asset="USDT") or {}
            free = float(bal.get("free", 0.0))
            return free
        except Exception:
            self.logger.exception("Failed to fetch USDT balance from Binance")
            return None
    
    def calculate_position_size(self):
        """Calculate position size as percentage of available USDT balance."""
        free_usdt = self.get_free_usdt()
        
        if free_usdt is None:
            # Fallback when API fails
            fallback = self.MIN_SAFE_FALLBACK_USDT
            if self.config.max_position_size is not None:
                fallback = min(fallback, self.config.max_position_size)
            self.logger.warning(f"Using fallback position size: {fallback:.2f} USDT due to balance fetch error")
            return fallback
        
        # Calculate percentage-based position size
        pct = self.config.position_size_percentage / 100.0
        size_usdt = free_usdt * pct
        
        # Apply optional ceiling (safety cap)
        if self.config.max_position_size is not None and size_usdt > self.config.max_position_size:
            self.logger.info(
                f"Position size capped by MAX_POSITION_SIZE: {size_usdt:.2f} -> {self.config.max_position_size:.2f} USDT"
            )
            size_usdt = self.config.max_position_size
        
        self.logger.info(
            f"Balance free USDT: {free_usdt:.2f} | Target position: {size_usdt:.2f} USDT ({self.config.position_size_percentage:.2f}%)"
        )
        return size_usdt
    
    def calculate_stop_loss(self, entry_price, direction='long'):
        """Calculate stop loss price."""
        if direction == 'long':
            return entry_price * (1 - self.stop_loss_pct)
        else:
            return entry_price * (1 + self.stop_loss_pct)
    
    def calculate_take_profit(self, entry_price, direction='long'):
        """Calculate take profit price."""
        if direction == 'long':
            return entry_price * (1 + self.take_profit_pct)
        else:
            return entry_price * (1 - self.take_profit_pct)
