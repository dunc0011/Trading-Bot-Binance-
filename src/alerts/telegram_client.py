"""
Telegram Alert Client
Send trade notifications and handle interactive commands
"""
import logging
import asyncio
from typing import Dict, Optional
import requests
from datetime import datetime


logger = logging.getLogger(__name__)


class TelegramClient:
    """Send alerts and handle commands via Telegram."""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.logger = logging.getLogger(__name__)
        self.enabled = bool(token and chat_id)
        
        if self.enabled:
            self.logger.info("Telegram alerts enabled")
        else:
            self.logger.info("Telegram alerts disabled (no token/chat_id)")
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram."""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=5)
            
            if response.status_code == 200:
                return True
            else:
                self.logger.error(f"Telegram API error: {response.text}")
                return False
        
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def send_trade_alert(self, trade: Dict) -> bool:
        """Send trade execution alert."""
        symbol = trade.get('symbol', 'UNKNOWN')
        action = trade.get('action', 'UNKNOWN')
        price = trade.get('price', 0)
        size = trade.get('size', 0)
        confidence = trade.get('ml_confidence', 0) * 100
        reason = trade.get('reason', 'ML signal')
        
        emoji = "🟢" if action == "BUY" else "🔴"
        
        message = f"""
{emoji} <b>{action} {symbol}</b>

💰 Price: ${price:.2f}
📊 Size: ${size:.0f}
🎯 Confidence: {confidence:.0f}%
💡 Reason: {reason}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
    
    def send_position_close_alert(self, trade: Dict) -> bool:
        """Send position close alert with P&L."""
        symbol = trade.get('symbol', 'UNKNOWN')
        entry_price = trade.get('entry_price', 0)
        exit_price = trade.get('exit_price', 0)
        pnl_pct = trade.get('pnl_pct', 0)
        pnl_usd = trade.get('pnl', 0)
        reason = trade.get('reason', 'Exit')
        
        emoji = "💚" if pnl_pct > 0 else "❌"
        sign = "+" if pnl_pct > 0 else ""
        
        message = f"""
{emoji} <b>CLOSED {symbol}</b>

📈 Entry: ${entry_price:.2f}
📉 Exit: ${exit_price:.2f}
💵 P&L: {sign}{pnl_pct:.2f}% (${sign}{pnl_usd:.2f})
💡 Reason: {reason}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
    
    def send_signal_rejected_alert(self, rejection: Dict) -> bool:
        """Send alert when signal is rejected."""
        symbol = rejection.get('symbol', 'UNKNOWN')
        action = rejection.get('action', 'UNKNOWN')
        reason = rejection.get('reason', 'Unknown')
        
        # Only alert on interesting rejections
        important_reasons = [
            'Max positions',
            'Portfolio limit',
            'Drawdown limit',
            'Heavy sell pressure',
            'At resistance'
        ]
        
        if not any(r in reason for r in important_reasons):
            return False  # Don't spam for minor rejections
        
        message = f"""
⚠️ <b>Signal Rejected</b>

🔸 {symbol} {action}
❌ Reason: {reason}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
    
    def send_daily_summary(self, summary: Dict) -> bool:
        """Send daily performance summary."""
        total_trades = summary.get('total_trades', 0)
        winning_trades = summary.get('winning_trades', 0)
        win_rate = summary.get('win_rate', 0) * 100
        total_pnl = summary.get('total_pnl', 0)
        open_positions = summary.get('open_positions', 0)
        
        emoji = "📊" if total_pnl >= 0 else "📉"
        sign = "+" if total_pnl >= 0 else ""
        
        message = f"""
{emoji} <b>Daily Summary</b>

📈 Trades: {total_trades} ({winning_trades}W / {total_trades - winning_trades}L)
🎯 Win Rate: {win_rate:.1f}%
💵 Total P&L: ${sign}{total_pnl:.2f}
📊 Open Positions: {open_positions}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
    
    def send_error_alert(self, error_msg: str) -> bool:
        """Send critical error alert."""
        message = f"""
🚨 <b>ERROR ALERT</b>

{error_msg}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
    
    def send_bot_status(self, status: str, details: str = "") -> bool:
        """Send bot status update."""
        emoji = "✅" if status == "RUNNING" else "⏸️" if status == "STOPPED" else "⚠️"
        
        message = f"""
{emoji} <b>Bot Status: {status}</b>

{details}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_message(message)
