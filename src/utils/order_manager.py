"""
Order Execution Manager
"""
import logging
from binance.exceptions import BinanceAPIException


class OrderManager:
    """Handles order execution and management."""
    
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.active_orders = {}
    
    async def execute_order(self, signal):
        """
        Execute a trading order based on signal.
        
        Args:
            signal: Trading signal dictionary
            
        Returns:
            dict: Order result
        """
        try:
            symbol = self.config.symbol
            side = signal['action']  # BUY or SELL
            
            # Get current price and calculate quantity
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
            
            # Calculate quantity (simplified)
            quantity = self.config.max_position_size / current_price
            quantity = round(quantity, 6)  # Round to appropriate precision
            
            self.logger.info(f"Executing {side} order: {quantity} {symbol} @ {current_price}")
            
            # Place market order
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            self.logger.info(f"Order placed successfully: {order['orderId']}")
            self.active_orders[order['orderId']] = order
            
            return order
            
        except BinanceAPIException as e:
            self.logger.error(f"Binance API error placing order: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error placing order: {e}", exc_info=True)
            raise
    
    def get_order_status(self, order_id):
        """Get status of an order."""
        try:
            order = self.client.get_order(
                symbol=self.config.symbol,
                orderId=order_id
            )
            return order
        except BinanceAPIException as e:
            self.logger.error(f"Error getting order status: {e}")
            return None
    
    def cancel_order(self, order_id):
        """Cancel an active order."""
        try:
            result = self.client.cancel_order(
                symbol=self.config.symbol,
                orderId=order_id
            )
            self.logger.info(f"Order {order_id} cancelled")
            return result
        except BinanceAPIException as e:
            self.logger.error(f"Error cancelling order: {e}")
            return None
