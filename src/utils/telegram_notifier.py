"""
Telegram Notification Utility
"""
import logging
import asyncio
from typing import Optional
import aiohttp


class TelegramNotifier:
    """Send notifications to Telegram via Bot API."""
    
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.enabled = enabled and bot_token and chat_id
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger(__name__)
        
        if not self.enabled:
            self.logger.info("Telegram notifications disabled")
        else:
            self.logger.info(f"Telegram notifications enabled for chat ID: {chat_id}")
    
    async def send(self, message: str, parse_mode: str = 'Markdown') -> bool:
        """
        Send a message to Telegram.
        
        Args:
            message: Message text to send
            parse_mode: 'Markdown' or 'HTML' or None
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    'chat_id': self.chat_id,
                    'text': message,
                    'parse_mode': parse_mode
                }
                
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self.logger.debug("Telegram message sent successfully")
                        return True
                    else:
                        error_text = await resp.text()
                        self.logger.error(f"Telegram API error ({resp.status}): {error_text}")
                        return False
                        
        except asyncio.TimeoutError:
            self.logger.error("Telegram notification timeout")
            return False
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_signal(self, signal: dict, symbol: str) -> bool:
        """
        Send a formatted trading signal notification.
        
        Args:
            signal: Signal dict with action, price, reason, indicators
            symbol: Trading pair symbol
            
        Returns:
            True if sent successfully
        """
        action = signal.get('action', 'UNKNOWN')
        price = signal.get('price', 0)
        reason = signal.get('reason', 'No reason provided')
        
        # Build message
        emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        
        message = f"{emoji} *{action} SIGNAL*\n"
        message += f"📊 Symbol: `{symbol}`\n"
        message += f"💰 Price: `${price:.2f}`\n"
        message += f"📝 Reason: {reason}\n"
        
        # Add indicators if available
        indicators = signal.get('indicators', {})
        if indicators:
            message += "\n📈 *Indicators:*\n"
            for key, value in indicators.items():
                if isinstance(value, (int, float)):
                    message += f"  • {key}: `{value:.4f}`\n"
                else:
                    message += f"  • {key}: `{value}`\n"
        
        return await self.send(message)
    
    async def send_order(self, order: dict, action: str, symbol: str) -> bool:
        """
        Send a formatted order execution notification.
        
        Args:
            order: Order response from Binance API
            action: BUY or SELL
            symbol: Trading pair symbol
            
        Returns:
            True if sent successfully
        """
        emoji = "✅" if order else "❌"
        
        if order:
            order_id = order.get('orderId', 'UNKNOWN')
            price = order.get('price', order.get('fills', [{}])[0].get('price', 'N/A'))
            qty = order.get('executedQty', order.get('origQty', 'N/A'))
            
            message = f"{emoji} *ORDER EXECUTED*\n"
            message += f"📊 Symbol: `{symbol}`\n"
            message += f"🔄 Action: `{action}`\n"
            message += f"🆔 Order ID: `{order_id}`\n"
            message += f"💰 Price: `{price}`\n"
            message += f"📦 Quantity: `{qty}`\n"
        else:
            message = f"{emoji} *ORDER FAILED*\n"
            message += f"📊 Symbol: `{symbol}`\n"
            message += f"🔄 Action: `{action}`\n"
            message += f"⚠️ Order was not placed (check logs for details)\n"
        
        return await self.send(message)
    
    async def send_error(self, error_msg: str, context: str = "") -> bool:
        """
        Send an error notification.
        
        Args:
            error_msg: Error message
            context: Optional context about where the error occurred
            
        Returns:
            True if sent successfully
        """
        message = f"⚠️ *BOT ERROR*\n"
        if context:
            message += f"📍 Context: {context}\n"
        message += f"❌ Error: `{error_msg}`\n"
        
        return await self.send(message)
    
    async def send_status(self, status: str, details: Optional[dict] = None) -> bool:
        """
        Send a bot status notification.
        
        Args:
            status: Status message (e.g., "Bot Started", "Bot Stopped")
            details: Optional dict with additional details
            
        Returns:
            True if sent successfully
        """
        message = f"🤖 *{status.upper()}*\n"
        
        if details:
            for key, value in details.items():
                message += f"  • {key}: `{value}`\n"
        
        return await self.send(message)
