"""
Main Trading Bot Logic
"""
import logging
import asyncio
from binance.client import Client
from binance.exceptions import BinanceAPIException

from strategies.simple_strategy import SimpleStrategy
from strategies.ml_ema_strategy import MLEMAStrategy
from strategies.scalping_strategy import ScalpingStrategy
from strategies.mean_reversion_strategy import MeanReversionStrategy
from utils.risk_manager import RiskManager
from utils.order_manager import OrderManager
from utils.telegram_notifier import TelegramNotifier


class TradingBot:
    """Main trading bot that coordinates strategy and execution."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize Binance client
        if config.trading_mode == "testnet":
            self.client = Client(
                config.api_key,
                config.api_secret,
                testnet=True
            )
        else:
            self.client = Client(
                config.api_key,
                config.api_secret
            )
        
        # Initialize components based on strategy selection
        if config.strategy == 'ml_ema':
            self.logger.info("Initializing ML EMA Strategy")
            self.strategy = MLEMAStrategy(config)
        elif config.strategy == 'scalping':
            self.logger.info("Initializing FAST Scalping Strategy (RSI + EMA)")
            self.strategy = ScalpingStrategy(config)
        elif config.strategy == 'mean_reversion':
            self.logger.info("Initializing Mean Reversion ML Strategy")
            self.strategy = MeanReversionStrategy(config)
        else:
            self.logger.info("Initializing Simple SMA Strategy")
            self.strategy = SimpleStrategy(config)
        
        self.risk_manager = RiskManager(config, self.client)
        self.order_manager = OrderManager(self.client, config)
        
        # Initialize Telegram notifier
        self.telegram = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            enabled=config.telegram_enabled
        )
        
        self.is_running = False
    
    async def start(self):
        """Start the trading bot."""
        self.is_running = True
        self.logger.info("Bot started successfully")
        
        try:
            # Verify connection
            account = self.client.get_account()
            self.logger.info(f"Connected to Binance - Account status: {account['accountType']}")
            
            # Send startup notification
            await self.telegram.send_status("Bot Started", {
                "Symbol": self.config.symbol,
                "Timeframe": self.config.timeframe,
                "Strategy": self.config.strategy,
                "Mode": "DRY RUN" if self.config.dry_run else "LIVE",
                "Trading Mode": self.config.trading_mode
            })
            
            # Main trading loop  
            check_interval = 10 if self.config.strategy == 'scalping' else 60  # Fast checks for scalping
            self.logger.info(f"Trading cycle interval: {check_interval}s")
            
            while self.is_running:
                await self.trading_cycle()
                await asyncio.sleep(check_interval)
                
        except BinanceAPIException as e:
            self.logger.error(f"Binance API error: {e}")
            await self.telegram.send_error(str(e), context="Binance API")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            await self.telegram.send_error(str(e), context="Bot startup/main loop")
            raise
    
    async def trading_cycle(self):
        """Execute one trading cycle."""
        try:
            # Get market data
            klines = self.client.get_klines(
                symbol=self.config.symbol,
                interval=self.config.timeframe,
                limit=100
            )
            
            # Analyze with strategy
            signal = self.strategy.analyze(klines)
            
            if signal:
                self.logger.info(f"Signal detected: {signal['action']} at {signal['price']}")
                
                # Send signal notification
                await self.telegram.send_signal(signal, self.config.symbol)
                
                # Check risk management
                if self.risk_manager.check_risk(signal):
                    # Calculate position size dynamically
                    if signal['action'] == 'BUY':
                        position_usdt = self.risk_manager.calculate_position_size()
                        self.logger.info(f"Placing BUY order with position size: ${position_usdt:.2f} USDT")
                        order = await self.order_manager.execute_order(
                            symbol=self.config.symbol,
                            side='BUY',
                            position_usdt=position_usdt,
                            price=signal.get('price')
                        )
                    else:
                        # SELL: use available balance
                        self.logger.info(f"Placing SELL order with available balance")
                        order = await self.order_manager.execute_order(
                            symbol=self.config.symbol,
                            side='SELL',
                            price=signal.get('price')
                        )
                    
                    # Send order notification
                    await self.telegram.send_order(order, signal['action'], self.config.symbol)
                    
                    if order:
                        self.logger.info(f"✅ Order executed: {order.get('orderId', 'UNKNOWN')}")
                    else:
                        self.logger.warning("Order was not placed (likely below minimum notional)")
                else:
                    self.logger.warning("Signal rejected by risk manager")
            
        except Exception as e:
            self.logger.error(f"Error in trading cycle: {e}", exc_info=True)
            await self.telegram.send_error(str(e), context="Trading cycle")
    
    async def stop(self):
        """Stop the trading bot."""
        self.is_running = False
        self.logger.info("Bot stopping...")
        await self.telegram.send_status("Bot Stopped")
