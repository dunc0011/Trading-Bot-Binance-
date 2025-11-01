"""
Real-time Position Monitor with WebSocket Streaming

Monitors open positions in real-time using Binance WebSocket bookTicker streams
and executes exits instantly when profit targets or stop losses are hit.
"""
import asyncio
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from binance.streams import ThreadedWebsocketManager


@dataclass
class PositionState:
    """Internal state for a monitored position"""
    symbol: str
    entry_price: float
    base_qty: float
    remaining_qty: float
    highest_price: float
    trailing_stop_price: float = 0.0  # Cached stop that only moves UP
    partial1_done: bool = False
    partial2_done: bool = False
    executing: bool = False
    closed: bool = False
    opened_ts: float = field(default_factory=time.time)
    last_update_ts: float = field(default_factory=time.time)
    
    def __post_init__(self):
        # asyncio.Lock can't be pickled, so create it after init
        # Don't create lock here - will be created in async context
        self.lock = None


@dataclass
class PriceTick:
    """Real-time price data from WebSocket"""
    bid: float
    ask: float
    ts: float


class RealtimePositionMonitor:
    """
    Real-time position monitor using WebSocket streams.
    
    Features:
    - Sub-second monitoring via Binance bookTicker WebSocket
    - Dynamic subscription management (subscribe/unsubscribe on position open/close)
    - Instant exit execution when profit targets or stops hit
    - Automatic fallback to REST polling if WebSocket fails
    - Thread-safe price cache and position state management
    """
    
    def __init__(self, client, order_manager, config, logger=None, on_position_closed=None, telegram=None):
        self.client = client
        self.order_manager = order_manager
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.on_position_closed = on_position_closed  # Callback when position closed
        self.telegram = telegram  # Telegram notifier for alerts
        
        # Position tracking (async-safe)
        self._positions: Dict[str, PositionState] = {}
        # Don't create lock here - will be created in async context
        self._positions_lock = None
        
        # Price cache (thread-safe for WS callback)
        self._price_cache: Dict[str, PriceTick] = {}
        self._price_lock = threading.Lock()
        
        # WebSocket manager
        self._twm: Optional[ThreadedWebsocketManager] = None
        self._twm_init_lock = threading.Lock()
        self._twm_started = threading.Event()
        self._socket_id: Optional[str] = None
        self._subscribed: Set[str] = set()
        self._ws_running = False
        self._ws_failure = False
        
        # Event coordination (create in async context)
        self._resubscribe_event = None
        self._price_event = None
        self._stop = None
        
        # Tasks
        self._monitor_task: Optional[asyncio.Task] = None
        self._ws_task: Optional[asyncio.Task] = None
        
        # Statistics
        self._stats = {
            'tp1_exits': 0,
            'tp2_exits': 0,
            'sl_exits': 0,
            'last_stats_log': time.time()
        }
    
    async def start(self):
        """Start the real-time monitor"""
        self.loop = asyncio.get_running_loop()
        # Create locks and events in async context
        self._positions_lock = asyncio.Lock()
        self._resubscribe_event = asyncio.Event()
        self._price_event = asyncio.Event()
        self._stop = asyncio.Event()
        await self._start_ws()
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="rtm.monitor")
        self._ws_task = asyncio.create_task(self._ws_supervisor_loop(), name="rtm.ws_supervisor")
        self.logger.info("✅ RTM: Real-time Position Monitor started")
    
    async def stop(self):
        """Stop the real-time monitor and cleanup"""
        self.logger.info("🛑 RTM: Stopping...")
        self._stop.set()
        
        # Cancel tasks
        for task in [self._monitor_task, self._ws_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close WebSocket
        try:
            if self._socket_id and self._twm:
                self._twm.stop_socket(self._socket_id)
                self._socket_id = None
            if self._twm:
                self._twm.stop()
                self._twm = None
        except Exception as e:
            self.logger.warning(f"RTM cleanup warning: {e}")
        
        self.logger.info("✅ RTM: Stopped")
    
    async def register_position(self, symbol: str, entry_price: float, qty: float, entry_fee_usdt: float = 0.0):
        """Register a new position for real-time monitoring"""
        async with self._positions_lock:
            # Calculate effective entry price that accounts for fees
            # We need to exit at a price that covers: entry fee + exit fee (estimated)
            estimated_exit_fee = entry_fee_usdt  # Assume exit fee similar to entry
            total_fees = entry_fee_usdt + estimated_exit_fee
            fee_adjusted_entry = entry_price + (total_fees / qty)

            if symbol in self._positions and not self._positions[symbol].closed:
                # CRITICAL FIX: Update entry price and qty for re-entries
                old_entry = self._positions[symbol].entry_price
                if abs(old_entry - entry_price) > 0.01:  # Price changed significantly
                    self.logger.warning(f"⚠️ RTM: {symbol} ENTRY PRICE UPDATED ${old_entry:.2f} → ${entry_price:.2f} (re-entry detected)")
                    self._positions[symbol].entry_price = fee_adjusted_entry  # Use fee-adjusted
                    self._positions[symbol].base_qty = qty
                    self._positions[symbol].remaining_qty = qty
                    self._positions[symbol].highest_price = fee_adjusted_entry  # Start from break-even
                    self._positions[symbol].trailing_stop_price = 0.0  # Reset stop
                    self._positions[symbol].opened_ts = time.time()
                else:
                    self.logger.debug(f"RTM: {symbol} already tracked at same price")
                return

            ps = PositionState(
                symbol=symbol,
                entry_price=fee_adjusted_entry,  # Use fee-adjusted entry
                base_qty=qty,
                remaining_qty=qty,
                highest_price=fee_adjusted_entry  # Start from break-even after fees
            )
            # Create lock for this position
            ps.lock = asyncio.Lock()
            self._positions[symbol] = ps

            fee_impact_pct = ((fee_adjusted_entry - entry_price) / entry_price) * 100
            self.logger.info(
                f"📍 RTM: Tracking {symbol} | Entry: ${entry_price:.2f} | "
                f"Fee-adjusted break-even: ${fee_adjusted_entry:.2f} (+{fee_impact_pct:.2f}%) | Qty: {qty:.8f}"
            )

        # Trigger WebSocket resubscription
        self._trigger_resubscribe()
    
    async def unregister_position(self, symbol: str):
        """Unregister a position (closed externally)"""
        async with self._positions_lock:
            if symbol in self._positions:
                self._positions[symbol].closed = True
                del self._positions[symbol]
                self.logger.info(f"📍 RTM: Untracked {symbol}")
        
        # Trigger WebSocket resubscription
        self._trigger_resubscribe()
    
    async def get_position_data(self, symbol: str) -> Optional[Dict]:
        """Get live peak and trailing stop for a position"""
        async with self._positions_lock:
            ps = self._positions.get(symbol)
        
        if not ps or ps.closed:
            return None
        
        # Return cached trailing stop (only moves up, never recalculates down)
        return {
            'peak_price': ps.highest_price,
            'trailing_stop': ps.trailing_stop_price if ps.trailing_stop_price > 0 else ps.entry_price * (1.0 - self.config.hard_stop_loss_pct)
        }
    
    def _trigger_resubscribe(self):
        """Signal WebSocket supervisor to resubscribe (thread-safe)"""
        if self.loop:
            self.loop.call_soon_threadsafe(self._resubscribe_event.set)
    
    def _start_twm_sync(self, testnet: bool):
        """Synchronous TWM initialization (runs in background thread)"""
        try:
            with self._twm_init_lock:
                if self._twm is None:
                    self._twm = ThreadedWebsocketManager(
                        api_key=self.config.api_key,
                        api_secret=self.config.api_secret,
                        testnet=testnet
                    )
                    self._twm.start()
                    self._twm_started.set()
                    self.logger.info(f"📡 RTM: WebSocket manager started (testnet={testnet})")
        except Exception as e:
            self.logger.error(f"RTM: Failed to start WebSocket: {e}", exc_info=True)
            self._ws_failure = True
            self._twm_started.set()  # Unblock waiter even on failure
    
    async def _start_ws(self):
        """Initialize WebSocket manager asynchronously"""
        if self._twm is None and not self._twm_started.is_set():
            testnet = self.config.trading_mode == "testnet"
            
            # Start TWM in a dedicated background thread to avoid event loop conflicts
            # (ThreadedWebsocketManager.start() uses asyncio.run() internally)
            thread = threading.Thread(
                target=self._start_twm_sync,
                args=(testnet,),
                daemon=True,
                name="rtm-twm-init"
            )
            thread.start()
            
            # Wait for TWM to start (non-blocking)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._twm_started.wait, 5.0)  # 5s timeout
            
            if self._ws_failure or self._twm is None:
                self.logger.warning("RTM: WebSocket initialization failed, using REST fallback only")
                return
        
        await self._resubscribe()
    
    def _ws_callback(self, msg):
        """
        WebSocket callback (runs in TWM thread).
        Updates price cache and signals monitor loop.
        """
        try:
            # Handle multiplex wrapper
            data = msg.get("data", msg)
            
            # Validate bookTicker message
            if data.get("e") not in (None, "bookTicker") or "b" not in data:
                return
            
            symbol = data["s"]
            bid = float(data["b"])
            ask = float(data["a"])
            ts = time.time()
            
            # Update price cache (thread-safe)
            with self._price_lock:
                self._price_cache[symbol] = PriceTick(bid=bid, ask=ask, ts=ts)
            
            # Wake up monitor loop immediately
            if self.loop:
                self.loop.call_soon_threadsafe(self._price_event.set)
        
        except Exception as e:
            self.logger.error(f"RTM: WebSocket callback error: {e}", exc_info=True)
            self._ws_failure = True
            if self.loop:
                self.loop.call_soon_threadsafe(self._price_event.set)
    
    async def _resubscribe(self):
        """Subscribe to bookTicker streams for all tracked positions"""
        async with self._positions_lock:
            symbols = sorted(self._positions.keys())
        
        streams = [f"{s.lower()}@bookTicker" for s in symbols]
        
        # No positions - close socket
        if not streams:
            if self._socket_id and self._twm:
                try:
                    self._twm.stop_socket(self._socket_id)
                except:
                    pass
                self._socket_id = None
                self._subscribed = set()
                self.logger.debug("RTM: No positions, WebSocket closed")
            return
        
        # Check if resubscription needed
        current_symbols = set(s.lower() for s in symbols)
        subscribed_symbols = set(x.split("@")[0] for x in self._subscribed)
        
        if current_symbols == subscribed_symbols:
            return  # No change
        
        # Restart socket with new streams
        try:
            if self._socket_id:
                self._twm.stop_socket(self._socket_id)
            
            self._socket_id = self._twm.start_multiplex_socket(
                callback=self._ws_callback,
                streams=streams
            )
            self._subscribed = set(streams)
            self._ws_running = True
            self._ws_failure = False
            self.logger.info(f"📡 RTM: Subscribed to {len(streams)} stream(s): {symbols}")
        
        except Exception as e:
            self._ws_running = False
            self._ws_failure = True
            self.logger.error(f"RTM: WebSocket subscribe error: {e}")
    
    async def _ws_supervisor_loop(self):
        """Monitor WebSocket health and handle reconnections"""
        while not self._stop.is_set():
            try:
                # Wait for resubscribe signal or timeout for health check
                timeout = self.config.websocket_reconnect_delay
                await asyncio.wait_for(self._resubscribe_event.wait(), timeout=timeout)
                self._resubscribe_event.clear()
                await self._resubscribe()
            
            except asyncio.TimeoutError:
                # Periodic health check
                if self._ws_failure:
                    self.logger.warning("RTM: WebSocket failure detected, reconnecting...")
                    await self._resubscribe()
            
            except asyncio.CancelledError:
                break
            
            except Exception as e:
                self.logger.exception(f"RTM: WebSocket supervisor error: {e}")
                await asyncio.sleep(self.config.websocket_reconnect_delay)
    
    async def _monitor_loop(self):
        """Main monitoring loop - checks positions at high frequency"""
        tick_s = max(0.05, min(1.0, self.config.monitor_tick_ms / 1000.0))
        self.logger.info(f"⚡ RTM: Monitor loop started (tick: {tick_s*1000:.0f}ms)")
        
        while not self._stop.is_set():
            try:
                # Event-driven wakeup (price update) or periodic tick
                try:
                    await asyncio.wait_for(self._price_event.wait(), timeout=tick_s)
                    self._price_event.clear()
                except asyncio.TimeoutError:
                    pass
                
                # Evaluate all positions
                await self._evaluate_all_positions()
                
                # Log stats periodically
                await self._log_stats_if_due()
            
            except asyncio.CancelledError:
                break
            
            except Exception as e:
                self.logger.exception(f"RTM: Monitor loop error: {e}")
                await asyncio.sleep(0.25)
    
    async def _evaluate_all_positions(self):
        """Check all tracked positions for exit conditions"""
        async with self._positions_lock:
            symbols = list(self._positions.keys())
        
        now = time.time()
        
        for sym in symbols:
            # Get position (with lock)
            async with self._positions_lock:
                ps = self._positions.get(sym)
            
            if not ps or ps.closed:
                continue
            
            # Process position atomically
            async with ps.lock:
                if ps.executing or ps.closed or ps.remaining_qty <= 0:
                    continue
                
                # Get price from cache or REST fallback
                price = await self._get_price(sym, ps, now)
                if price is None:
                    continue
                
                ps.last_update_ts = now
                
                # Track highest price for trailing stop
                if price > ps.highest_price:
                    old_high = ps.highest_price
                    ps.highest_price = price
                    gain_pct = ((price / ps.entry_price) - 1.0) * 100
                    self.logger.info(f"🔼 {sym}: NEW HIGH ${price:.2f} (+{gain_pct:.2f}%) - was ${old_high:.2f}")
                
                # Apply exit logic
                await self._apply_exit_logic(ps, price)
    
    async def _get_price(self, symbol: str, ps: PositionState, now: float) -> Optional[float]:
        """Get current price from WebSocket cache or REST fallback"""
        # Try WebSocket cache first (only if WS is working)
        if not self._ws_failure:
            with self._price_lock:
                tick = self._price_cache.get(symbol)
            
            if tick and (now - tick.ts < 5.0):  # Use WS data if fresh (< 5s old)
                return tick.bid
        
        # Always use REST fallback if:
        # 1. WebSocket is broken
        # 2. No recent WebSocket data
        # 3. Been more than 1 second since last update
        if self._ws_failure or now - ps.last_update_ts >= self.config.monitor_poll_fallback_interval:
            try:
                # Use shorter timeout to prevent blocking
                import asyncio
                loop = asyncio.get_event_loop()
                ob = await loop.run_in_executor(None, lambda: self.client.get_orderbook_ticker(symbol=symbol))
                price = float(ob["bidPrice"])
                
                # Update cache
                with self._price_lock:
                    self._price_cache[symbol] = PriceTick(
                        bid=price,
                        ask=float(ob["askPrice"]),
                        ts=now
                    )
                
                return price
            
            except asyncio.TimeoutError:
                self.logger.warning(f"RTM: REST fallback timeout for {symbol}")
                return None
            except Exception as e:
                self.logger.warning(f"RTM: REST fallback failed for {symbol}: {e}")
                return None
        
        return None
    
    async def _apply_exit_logic(self, ps: PositionState, price: float):
        """Apply ONLY stop-loss below entry - let ML strategy handle exits above entry"""
        entry = ps.entry_price
        gain = (price / entry) - 1.0
        
        # ONLY ONE RULE: 3% stop-loss below entry
        # No trailing stops, no profit-taking - ML strategy decides when to sell
        stop_loss_price = entry * 0.97  # 3% below entry
        
        # Track peak for logging only (not for exit logic)
        if price > ps.highest_price:
            ps.highest_price = price
            gain_pct = gain * 100
            self.logger.info(f"🔼 {ps.symbol}: NEW HIGH ${price:.2f} (+{gain_pct:.2f}%)")
        
        # ONLY exit if stop-loss hit
        if price <= stop_loss_price:
            await self._exit_all(
                ps, 
                price, 
                reason=f"Stop-loss hit (3% below entry) | Loss: {gain*100:.2f}%"
            )
            self._stats['sl_exits'] += 1
            return
    
    async def _exit_all(self, ps: PositionState, mkt_price: float, reason: str):
        """Exit entire remaining position"""
        await self._exit_qty(ps, ps.remaining_qty, mkt_price, reason)
    
    async def _exit_qty(self, ps: PositionState, qty: float, mkt_price: float, reason: str):
        """Execute exit for specified quantity"""
        if qty <= 0 or ps.executing or ps.closed:
            return
        
        ps.executing = True
        
        try:
            msg_prefix = "⚡ REALTIME EXIT"
            
            if self.config.dry_run:
                self.logger.info(
                    f"{msg_prefix} [DRY RUN] {ps.symbol} | "
                    f"Qty: {qty:.8f} @ ${mkt_price:.6f} | {reason}"
                )
            else:
                # Execute market sell - handle both dict and single order manager
                if isinstance(self.order_manager, dict):
                    # Multi-pair bot: use per-symbol order manager
                    order_mgr = self.order_manager.get(ps.symbol)
                    if not order_mgr:
                        self.logger.error(f"No order manager for {ps.symbol}")
                        return
                else:
                    # Single-pair bot: use shared order manager
                    order_mgr = self.order_manager
                
                order = await order_mgr.execute_order(
                    symbol=ps.symbol,
                    side='SELL',
                    quantity=qty
                )
                
                # Extract exit fee
                exit_fee = order.get('total_fee_usdt', 0.0) if order else 0.0
                
                self.logger.info(
                    f"{msg_prefix} {ps.symbol} | "
                    f"SOLD {qty:.8f} @ ~${mkt_price:.6f} | Fee: ${exit_fee:.4f} | {reason}"
                )
                
                # Telegram notification handled by main bot via on_position_closed callback
            
            # Update remaining quantity
            ps.remaining_qty = round(ps.remaining_qty - qty, 8)
            
            if ps.remaining_qty <= 0:
                ps.closed = True
                self.logger.info(f"✅ RTM: {ps.symbol} position fully closed")
                
                # Notify bot that position was closed with exit details
                if self.on_position_closed:
                    try:
                        # Pass exit data to callback for logging (include exit fee)
                        exit_data = {
                            'symbol': ps.symbol,
                            'entry_price': ps.entry_price,
                            'exit_price': mkt_price,
                            'qty': qty,
                            'reason': reason,
                            'exit_fee_usdt': exit_fee if not self.config.dry_run else 0.0
                        }
                        await self.on_position_closed(exit_data)
                    except Exception as e:
                        self.logger.error(f"RTM: Error in on_position_closed callback: {e}")
        
        except Exception as e:
            self.logger.exception(f"RTM: Exit error for {ps.symbol}: {e}")
        
        finally:
            ps.executing = False
            
            # Trigger resubscription if position closed
            if ps.closed:
                self._trigger_resubscribe()
    
    async def _log_stats_if_due(self):
        """Periodically log monitoring statistics"""
        now = time.time()
        if now - self._stats['last_stats_log'] >= 30:  # Every 30 seconds
            async with self._positions_lock:
                n_positions = len(self._positions)
            
            ws_status = "🟢 Connected" if self._ws_running and not self._ws_failure else "🔴 Fallback"
            
            self.logger.info(
                f"📊 RTM Stats | Positions: {n_positions} | "
                f"Exits: TP1={self._stats['tp1_exits']} TP2={self._stats['tp2_exits']} SL={self._stats['sl_exits']} | "
                f"WS: {ws_status}"
            )
            
            self._stats['last_stats_log'] = now
