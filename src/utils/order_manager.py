"""
Order Execution Manager
"""
import logging
from decimal import Decimal, ROUND_DOWN
from binance.exceptions import BinanceAPIException


class OrderManager:
    """Handles order execution and management."""
    
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.active_orders = {}
        self.active_stop_orders = {}  # Track stop-loss orders by symbol
        self.symbol_info_cache = {}  # Cache symbol filters
        self.use_limit_orders = False  # Use market orders for instant execution
    
    def _get_symbol_filters(self, symbol):
        """Get LOT_SIZE and NOTIONAL filters for a symbol."""
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]
        
        try:
            info = self.client.get_symbol_info(symbol)
            filters = {}
            
            for f in info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    filters['lot_size'] = {
                        'min_qty': float(f['minQty']),
                        'max_qty': float(f['maxQty']),
                        'step_size': float(f['stepSize'])
                    }
                elif f['filterType'] == 'NOTIONAL':
                    filters['min_notional'] = float(f.get('minNotional', 0))
                elif f['filterType'] == 'MIN_NOTIONAL':
                    filters['min_notional'] = float(f.get('minNotional', 0))
            
            self.symbol_info_cache[symbol] = filters
            return filters
        except Exception as e:
            self.logger.error(f"Error fetching symbol info: {e}")
            return {}
    
    def _round_quantity(self, quantity, step_size):
        """Round quantity to match step size."""
        precision = 0
        if step_size < 1:
            # Count decimal places
            precision = len(str(step_size).rstrip('0').split('.')[1])
        return round(quantity - (quantity % step_size), precision)
    
    def _round_price(self, price, tick_size):
        """Round price to match tick size."""
        precision = 0
        if tick_size < 1:
            precision = len(str(tick_size).rstrip('0').split('.')[1])
        return round(price - (price % tick_size), precision)
    
    def _floor_to_step(self, value, step):
        """Floor a value to the nearest step using Decimal for precision."""
        if step == 0:
            return value
        value_dec = Decimal(str(value))
        step_dec = Decimal(str(step))
        return float((value_dec // step_dec) * step_dec)
    
    def _get_enhanced_symbol_filters(self, symbol):
        """Get comprehensive symbol filters including all notional variants."""
        try:
            info = self.client.get_symbol_info(symbol)
            filters_dict = {f['filterType']: f for f in info.get('filters', [])}
            
            lot_filter = filters_dict.get('LOT_SIZE', {})
            price_filter = filters_dict.get('PRICE_FILTER', {})
            min_notional_filter = filters_dict.get('MIN_NOTIONAL') or filters_dict.get('NOTIONAL') or {}
            
            step_size = float(lot_filter.get('stepSize', '0.00000001'))
            min_qty = float(lot_filter.get('minQty', '0.00000000'))
            max_qty = float(lot_filter.get('maxQty', '9999999999.00000000'))
            tick_size = float(price_filter.get('tickSize', '0.00000001'))
            
            # Handle both MIN_NOTIONAL and NOTIONAL filter variants
            min_notional = float(
                min_notional_filter.get('minNotional')
                or min_notional_filter.get('notional')
                or '10.0'  # Conservative default
            )
            
            base_asset = info.get('baseAsset', symbol.replace('USDT', ''))
            
            self.logger.debug(
                f"Filters for {symbol}: stepSize={step_size}, minQty={min_qty}, "
                f"tickSize={tick_size}, minNotional={min_notional}"
            )
            
            return {
                'step_size': step_size,
                'min_qty': min_qty,
                'max_qty': max_qty,
                'tick_size': tick_size,
                'min_notional': min_notional,
                'base_asset': base_asset
            }
        except Exception as e:
            self.logger.error(f"Error fetching enhanced symbol filters: {e}")
            return {
                'step_size': 0.00000001,
                'min_qty': 0.00000001,
                'max_qty': 9999999999.0,
                'tick_size': 0.01,
                'min_notional': 10.0,
                'base_asset': symbol.replace('USDT', '')
            }
    
    def _qty_from_usdt(self, symbol, usdt_amount, price=None):
        """Convert USDT amount to base asset quantity respecting exchange filters."""
        try:
            # Get current price if not provided
            if price is None:
                ticker = self.client.get_symbol_ticker(symbol=symbol)
                price = float(ticker['price'])
            
            filters = self._get_enhanced_symbol_filters(symbol)
            
            # Calculate raw quantity
            qty = usdt_amount / price
            
            # Floor to step size
            qty = self._floor_to_step(qty, filters['step_size'])
            
            # Check minimum quantity
            if qty < filters['min_qty']:
                self.logger.warning(
                    f"Computed qty {qty:.8f} below minQty {filters['min_qty']:.8f} for {symbol}"
                )
                return None
            
            # Check minimum notional
            notional = qty * price
            if notional < filters['min_notional']:
                self.logger.warning(
                    f"Notional ${notional:.2f} below minNotional ${filters['min_notional']:.2f} for {symbol}. "
                    f"Increase POSITION_SIZE_PERCENTAGE or remove MAX_POSITION_SIZE cap."
                )
                return None
            
            self.logger.debug(
                f"Converted ${usdt_amount:.2f} USDT -> {qty:.8f} {filters['base_asset']} @ ${price:.2f} (notional: ${notional:.2f})"
            )
            
            return qty
        except Exception as e:
            self.logger.error(f"Error converting USDT to quantity: {e}", exc_info=True)
            return None
    
    def _get_free_base_asset(self, symbol):
        """Get available base asset balance for selling."""
        try:
            filters = self._get_enhanced_symbol_filters(symbol)
            base_asset = filters['base_asset']
            
            bal = self.client.get_asset_balance(asset=base_asset) or {}
            free = float(bal.get('free', 0.0))
            
            # Floor to step size
            free = self._floor_to_step(free, filters['step_size'])
            
            self.logger.debug(f"Free {base_asset} balance: {free:.8f}")
            return free
        except Exception as e:
            self.logger.error(f"Error fetching base asset balance: {e}", exc_info=True)
            return 0.0
    
    def _get_ticker_price(self, symbol):
        """Get current bid/ask prices."""
        try:
            ticker = self.client.get_orderbook_ticker(symbol=symbol)
            return {
                'bid': float(ticker['bidPrice']),
                'ask': float(ticker['askPrice']),
                'mid': (float(ticker['bidPrice']) + float(ticker['askPrice'])) / 2
            }
        except:
            # Fallback to simple ticker
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            return {'bid': price, 'ask': price, 'mid': price}
    
    async def execute_order(self, signal=None, symbol=None, side=None, position_usdt=None, quantity=None, price=None):
        """
        Execute a trading order based on signal or explicit parameters.
        
        Args:
            signal: Trading signal dictionary (legacy support)
            symbol: Trading symbol (optional, uses config.symbol if not provided)
            side: Order side - 'BUY' or 'SELL' (optional if signal provided)
            position_usdt: Position size in USDT (for BUY orders)
            quantity: Explicit quantity to trade (overrides position_usdt)
            price: Optional price hint for conversion
            
        Returns:
            dict: Order result, or None if order aborted
        """
        try:
            # Handle legacy signal-based calls
            if signal is not None:
                symbol = symbol or self.config.symbol
                side = signal['action']  # BUY or SELL
                price = signal.get('price')
                # Legacy: use old max_position_size logic if available
                if not position_usdt and not quantity:
                    ticker = self.client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    if hasattr(self.config, 'max_position_size') and self.config.max_position_size:
                        quantity = self.config.max_position_size / current_price
            else:
                # New explicit parameter style
                symbol = symbol or self.config.symbol
                if not side:
                    raise ValueError("Must provide 'side' (BUY or SELL) when not using signal")
            
            # Get current price if needed
            if not price:
                ticker = self.client.get_symbol_ticker(symbol=symbol)
                price = float(ticker['price'])
                current_price = price
            else:
                current_price = price
            
            # Determine quantity based on side and inputs
            if quantity is None:
                if side == 'BUY':
                    # BUY: use USDT-based sizing
                    if position_usdt is None:
                        raise ValueError("Must provide 'position_usdt' for BUY orders when quantity not specified")
                    quantity = self._qty_from_usdt(symbol, position_usdt, current_price)
                    if quantity is None:
                        self.logger.warning("Order aborted: computed notional below exchange minimum")
                        return None
                elif side == 'SELL':
                    # SELL: use available base asset balance
                    quantity = self._get_free_base_asset(symbol)
                    if quantity <= 0:
                        self.logger.warning(f"No {symbol} balance available to sell")
                        return None
                else:
                    raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'")
            
            # Get symbol filters (using legacy method for remaining logic)
            filters = self._get_symbol_filters(symbol)
            
            # Verify notional (already checked in _qty_from_usdt, but double-check for safety)
            notional = quantity * current_price
            min_notional = filters.get('min_notional', 10)
            
            if notional < min_notional:
                self.logger.warning(
                    f"Order notional ${notional:.2f} still below minimum ${min_notional:.2f} after sizing. Order aborted."
                )
                return None
            
            # Get current bid/ask for smart limit orders
            prices = self._get_ticker_price(symbol)
            
            # Determine order type and price
            if self.use_limit_orders and side == 'BUY':
                # For BUY: place limit at bid (or slightly above) to avoid paying spread
                limit_price = prices['bid'] + (prices['ask'] - prices['bid']) * 0.3  # 30% into spread
                if 'lot_size' in filters and 'tickSize' in str(filters):
                    # Get tick size from PRICE_FILTER
                    tick_size = 0.01  # Default
                    try:
                        info = self.client.get_symbol_info(symbol)
                        for f in info['filters']:
                            if f['filterType'] == 'PRICE_FILTER':
                                tick_size = float(f['tickSize'])
                                break
                    except:
                        pass
                    limit_price = self._round_price(limit_price, tick_size)
                
                order_type = 'LIMIT'
                order_price = limit_price
                self.logger.info(f"🎯 Executing SMART LIMIT {side}: {quantity} {symbol} @ ${order_price:.4f} (bid: ${prices['bid']:.4f}, ask: ${prices['ask']:.4f})")
            else:
                # For SELL or if limit disabled: use market
                order_type = 'MARKET'
                order_price = current_price
                self.logger.info(f"Executing {side} order: {quantity} {symbol} @ market (${current_price:.2f})")
            
            # Place order
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity
            }
            
            if order_type == 'LIMIT':
                order_params['price'] = order_price
                order_params['timeInForce'] = 'GTC'  # Good til cancelled
            
            if self.config.dry_run:
                self.logger.info(f"[DRY RUN] Would execute: {order_params}")
                return {
                    'orderId': 'DRY_RUN',
                    'symbol': symbol,
                    'side': side,
                    'type': order_type,
                    'executedQty': quantity,
                    'price': order_price if order_type == 'LIMIT' else current_price
                }
            
            order = self.client.create_order(**order_params)
            
            self.logger.info(f"✅ Order placed successfully: {order['orderId']}")
            self.active_orders[order['orderId']] = order
            
            # For BUY orders, immediately place stop-loss at exchange
            if side == 'BUY' and signal.get('stop_loss_price'):
                self._place_stop_loss(symbol, quantity, signal['stop_loss_price'], order)
            
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
    
    def _place_stop_loss(self, symbol, quantity, stop_price, parent_order):
        """Place stop-loss order at exchange level."""
        try:
            if self.config.dry_run:
                self.logger.info(f"[DRY RUN] Would place stop-loss at ${stop_price:.2f} for {quantity} {symbol}")
                return
            
            # Get tick size for price rounding
            filters = self._get_symbol_filters(symbol)
            tick_size = 0.01
            try:
                info = self.client.get_symbol_info(symbol)
                for f in info['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        tick_size = float(f['tickSize'])
                        break
            except:
                pass
            
            stop_price = self._round_price(stop_price, tick_size)
            limit_price = self._round_price(stop_price * 0.995, tick_size)  # Limit 0.5% below stop
            
            # Place STOP_LOSS_LIMIT order
            stop_order = self.client.create_order(
                symbol=symbol,
                side='SELL',
                type='STOP_LOSS_LIMIT',
                quantity=quantity,
                price=limit_price,
                stopPrice=stop_price,
                timeInForce='GTC'
            )
            
            self.active_stop_orders[symbol] = stop_order
            self.logger.info(f"🛡️ Stop-loss placed at ${stop_price:.2f} for {symbol} (order: {stop_order['orderId']})")
            return stop_order
        
        except BinanceAPIException as e:
            self.logger.error(f"Failed to place stop-loss: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error placing stop-loss: {e}", exc_info=True)
            return None
    
    def cancel_stop_loss(self, symbol):
        """Cancel active stop-loss order for symbol."""
        if symbol in self.active_stop_orders:
            try:
                order_id = self.active_stop_orders[symbol]['orderId']
                self.client.cancel_order(symbol=symbol, orderId=order_id)
                del self.active_stop_orders[symbol]
                self.logger.info(f"Stop-loss cancelled for {symbol}")
            except Exception as e:
                self.logger.error(f"Error cancelling stop-loss: {e}")
    
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
