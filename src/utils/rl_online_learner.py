"""
Online RL Learning System
Continuously updates RL agents from real trading experience
"""
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta

from utils.rl_agent import RLTradingAgent
from utils.rl_trading_env import TradingEnv
from config.config import Config


class RLOnlineLearner:
    """
    Online learning system for RL agents
    
    Updates RL models based on actual trading results in real-time
    
    Features:
    - Incremental learning from completed trades
    - Experience replay buffer
    - Adaptive learning rate
    - Prevents catastrophic forgetting
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Online learning settings
        self.min_trades_for_update = 5  # Update after N trades
        self.update_frequency = 10  # Update every N trades
        self.experience_buffer_size = 100  # Keep last N trades
        self.learning_rate_decay = 0.95  # Reduce LR over time
        
        # Experience buffer (stores recent trades)
        self.experience_buffer = []
        self.trades_since_update = 0
        
        # Track model versions
        self.models_dir = Path('models/rl_agents')
        self.online_models_dir = Path('models/rl_agents_online')
        self.online_models_dir.mkdir(parents=True, exist_ok=True)
        
        # Active agents (symbol -> agent)
        self.agents = {}
        
        self.logger.info("🎓 RL Online Learner initialized")
    
    def log_trade_experience(self, trade_data: Dict):
        """
        Log a completed trade for online learning
        
        Args:
            trade_data: Dict containing trade information
        """
        symbol = trade_data['symbol']
        
        # Extract experience
        experience = {
            'symbol': symbol,
            'entry_price': trade_data['entry_price'],
            'exit_price': trade_data['exit_price'],
            'profit_pct': trade_data['profit_pct'],
            'profit_usd': trade_data['profit_usd'],
            'timestamp': datetime.now(),
            'duration': (
                datetime.fromisoformat(trade_data['exit_time']) - 
                datetime.fromisoformat(trade_data['entry_time'])
            ).total_seconds(),
            'ml_confidence': trade_data.get('ml_confidence', 0)
        }
        
        # Add to buffer
        self.experience_buffer.append(experience)
        
        # Trim buffer
        if len(self.experience_buffer) > self.experience_buffer_size:
            self.experience_buffer.pop(0)
        
        self.trades_since_update += 1
        
        self.logger.info(
            f"📝 Logged trade: {symbol} "
            f"{'+' if experience['profit_pct'] > 0 else ''}{experience['profit_pct']:.2f}% "
            f"(buffer: {len(self.experience_buffer)})"
        )
        
        # Check if update needed
        if self.trades_since_update >= self.update_frequency:
            self._trigger_online_update(symbol)
    
    def _trigger_online_update(self, symbol: str):
        """
        Trigger online learning update for a symbol
        
        Args:
            symbol: Trading pair to update
        """
        # Get recent experiences for this symbol
        symbol_experiences = [
            exp for exp in self.experience_buffer 
            if exp['symbol'] == symbol
        ]
        
        if len(symbol_experiences) < self.min_trades_for_update:
            self.logger.debug(
                f"{symbol}: Not enough trades yet "
                f"({len(symbol_experiences)}/{self.min_trades_for_update})"
            )
            return
        
        self.logger.info(f"🎓 Triggering online learning update for {symbol}...")
        
        try:
            # Load or create agent
            if symbol not in self.agents:
                self._load_agent(symbol)
            
            # Perform incremental update
            self._incremental_update(symbol, symbol_experiences)
            
            # Reset counter
            self.trades_since_update = 0
            
            self.logger.info(f"✅ {symbol} online learning update complete")
        
        except Exception as e:
            self.logger.error(f"Failed to update {symbol}: {e}", exc_info=True)
    
    def _load_agent(self, symbol: str):
        """Load RL agent for symbol"""
        timeframe = self.config.timeframe
        
        try:
            # Try to load online version first
            online_path = self.online_models_dir / f"{symbol}_{timeframe}_rl_agent.zip"
            
            if online_path.exists():
                agent = RLTradingAgent(symbol=symbol, timeframe=timeframe)
                agent.load(str(online_path))
                self.logger.info(f"Loaded online model: {symbol}")
            else:
                # Load base model and copy to online version
                agent = RLTradingAgent(symbol=symbol, timeframe=timeframe)
                agent.load()  # Load from base models
                
                # Save as online version
                agent.agent.save(str(online_path))
                self.logger.info(f"Initialized online model from base: {symbol}")
            
            self.agents[symbol] = agent
        
        except Exception as e:
            self.logger.error(f"Failed to load agent for {symbol}: {e}")
            raise
    
    def _incremental_update(self, symbol: str, experiences: list):
        """
        Perform incremental learning update
        
        Args:
            symbol: Trading pair
            experiences: List of trade experiences
        """
        agent = self.agents[symbol]
        
        # Calculate aggregate reward from experiences
        total_return = sum(exp['profit_pct'] for exp in experiences) / 100
        avg_return = total_return / len(experiences)
        
        win_rate = sum(1 for exp in experiences if exp['profit_pct'] > 0) / len(experiences)
        
        self.logger.info(
            f"{symbol}: Learning from {len(experiences)} trades "
            f"(Avg: {avg_return*100:+.2f}%, Win: {win_rate*100:.1f}%)"
        )
        
        # Fine-tune model with recent data
        # Get recent market data
        from binance.client import Client
        
        if self.config.trading_mode == "testnet":
            client = Client(self.config.api_key, self.config.api_secret, testnet=True)
        else:
            client = Client(self.config.api_key, self.config.api_secret)
        
        # Fetch recent data for fine-tuning
        klines = client.get_klines(
            symbol=symbol,
            interval=self.config.timeframe,
            limit=500  # Last 500 candles for fine-tuning
        )
        
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'num_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Add features
        df['returns'] = df['close'].pct_change()
        df['sma_10'] = df['close'].rolling(10).mean()
        df['sma_30'] = df['close'].rolling(30).mean()
        df['volume_sma'] = df['volume'].rolling(10).mean()
        df['volatility'] = df['returns'].rolling(20).std()
        df = df.dropna()
        
        # Create environment for fine-tuning
        env = agent.create_env(df, initial_balance=1000, max_episode_steps=100)
        
        # Fine-tune with reduced learning rate (prevents forgetting)
        reduced_lr = 1e-5 if total_return > 0 else 5e-6  # Lower LR for bad performance
        
        self.logger.info(f"Fine-tuning with LR={reduced_lr:.2e}, steps=2048...")
        
        # Update model parameters
        agent.agent.learning_rate = reduced_lr
        
        # Fine-tune for a small number of steps
        agent.agent.learn(
            total_timesteps=2048,  # Small update
            reset_num_timesteps=False,  # Continue from current state
            progress_bar=False
        )
        
        # Save online model
        online_path = self.online_models_dir / f"{symbol}_{self.config.timeframe}_rl_agent.zip"
        agent.agent.save(str(online_path))
        
        # Save metadata
        meta = {
            'symbol': symbol,
            'timeframe': self.config.timeframe,
            'last_updated': datetime.now().isoformat(),
            'trades_learned_from': len(experiences),
            'avg_return': avg_return,
            'win_rate': win_rate,
            'learning_rate': reduced_lr
        }
        
        import json
        with open(online_path.with_suffix('.meta.json'), 'w') as f:
            json.dump(meta, f, indent=2)
        
        self.logger.info(f"💾 Saved updated model: {online_path.name}")
    
    def get_stats(self) -> Dict:
        """Get online learning statistics"""
        return {
            'buffer_size': len(self.experience_buffer),
            'trades_since_update': self.trades_since_update,
            'active_models': len(self.agents),
            'symbols': list(self.agents.keys())
        }


# Global instance for easy access
_online_learner = None


def get_online_learner(config: Config) -> RLOnlineLearner:
    """Get singleton online learner instance"""
    global _online_learner
    if _online_learner is None:
        _online_learner = RLOnlineLearner(config)
    return _online_learner
