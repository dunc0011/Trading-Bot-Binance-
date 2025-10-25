"""
Risk Management Module
"""
import logging


class RiskManager:
    """Manages risk and position sizing."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.max_position_size = config.max_position_size
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
    
    def calculate_position_size(self, signal):
        """Calculate position size based on risk parameters."""
        # Simple fixed position sizing
        # Can be enhanced with Kelly Criterion, risk-per-trade, etc.
        return self.max_position_size
    
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
