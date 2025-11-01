"""
RL Strategy - Uses trained Reinforcement Learning agents
"""
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict

from utils.rl_agent import RLTradingAgent
from utils.rl_trading_env import TradingEnv


class RLStrategy:
    """
    Strategy that uses trained RL agents for trading decisions
    
    Features:
    - Loads pre-trained RL agents
    - Converts market data to RL environment observations
    - Maps RL actions to trading signals
    - Supports multiple RL agents (ensemble)
    """
    
    def __init__(self, config):
        """
        Args:
            config: Bot configuration object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.symbol = config.symbol
        self.timeframe = config.timeframe
        
        # RL agent
        self.agent = None
        self.agent_loaded = False
        
        # Environment for feature extraction
        self.env = None
        
        # Position tracking
        self.position = None
        
        # Action mapping
        self.action_map = {
            0: 'HOLD',
            1: 'BUY',
            2: 'SELL',
            3: 'BUY_LARGE',
            4: 'SELL_TRAILING'
        }
        
        # Load agent
        self._load_agent()
    
    def _load_agent(self):
        """Load trained RL agent for this symbol/timeframe"""
        try:
            self.agent = RLTradingAgent(
                symbol=self.symbol,
                timeframe=self.timeframe
            )
            
            # Try to load existing model
            self.agent.load()
            self.agent_loaded = True
            
            self.logger.info(f"✅ Loaded RL agent for {self.symbol} {self.timeframe}")
        
        except FileNotFoundError:
            self.logger.warning(
                f"No trained RL model found for {self.symbol} {self.timeframe}. "
                f"Train one via web UI or CLI."
            )
            self.agent_loaded = False
        
        except Exception as e:
            self.logger.error(f"Failed to load RL agent: {e}", exc_info=True)
            self.agent_loaded = False
    
    def _prepare_observation(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """
        Prepare current market state as RL observation
        
        Args:
            df: Recent market data (OHLCV + features)
            
        Returns:
            Observation array or None if insufficient data
        """
        if len(df) < 30:  # Need at least 30 candles for features
            return None
        
        try:
            # Create temporary environment to extract observation
            if self.env is None:
                self.env = TradingEnv(
                    df=df,
                    initial_balance=10000,  # Dummy value
                    trading_fee=0.001,
                    max_position_size=1000,  # Dummy value
                    max_episode_steps=len(df)
                )
            
            # Get current observation (last state)
            self.env.df = df  # Update with latest data
            self.env.current_step = len(df) - 1
            
            obs = self.env._get_observation()
            
            return obs
        
        except Exception as e:
            self.logger.error(f"Error preparing observation: {e}", exc_info=True)
            return None
    
    def analyze(self, klines: list) -> Optional[Dict]:
        """
        Analyze market using RL agent
        
        Args:
            klines: List of kline data from Binance
            
        Returns:
            Signal dict or None
        """
        if not self.agent_loaded:
            self.logger.debug("RL agent not loaded, skipping analysis")
            return None
        
        try:
            # Convert klines to DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'num_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Add basic features (RL env expects these)
            df['returns'] = df['close'].pct_change()
            df['sma_10'] = df['close'].rolling(10).mean()
            df['sma_30'] = df['close'].rolling(30).mean()
            df['volume_sma'] = df['volume'].rolling(10).mean()
            df['volatility'] = df['returns'].rolling(20).std()
            
            # Fill NaN
            df = df.fillna(method='ffill').fillna(method='bfill').fillna(0)
            
            # Get observation
            obs = self._prepare_observation(df)
            
            if obs is None:
                self.logger.debug("Could not prepare observation")
                return None
            
            # Get action from RL agent
            action = self.agent.predict(obs, deterministic=True)
            action_name = self.agent.get_action_name(action)
            
            current_price = float(df['close'].iloc[-1])
            
            self.logger.info(
                f"RL Agent action: {action_name} "
                f"(price: ${current_price:.2f})"
            )
            
            # Map action to signal
            if action_name == 'BUY' and self.position is None:
                return {
                    'action': 'BUY',
                    'price': current_price,
                    'reason': 'RL agent suggests BUY',
                    'confidence': 0.75,  # RL agents are fairly confident
                    'indicators': {
                        'rl_action': action_name,
                        'rl_action_id': int(action),
                        'ml_confidence': 0.65  # Report confidence for position sizing
                    }
                }
            
            elif action_name == 'BUY_LARGE' and self.position is None:
                # Treat as high-confidence BUY
                return {
                    'action': 'BUY',
                    'price': current_price,
                    'reason': 'RL agent HIGH CONFIDENCE BUY',
                    'confidence': 0.90,
                    'indicators': {
                        'rl_action': action_name,
                        'rl_action_id': int(action),
                        'ml_confidence': 0.75  # High confidence for larger position
                    }
                }
            
            elif action_name == 'SELL' and self.position is not None:
                return {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': 'RL agent suggests SELL',
                    'confidence': 0.75,
                    'indicators': {
                        'rl_action': action_name,
                        'rl_action_id': int(action)
                    }
                }
            
            elif action_name == 'SELL_TRAILING' and self.position is not None:
                # Exit with trailing stop logic
                return {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': 'RL agent trailing stop exit',
                    'confidence': 0.85,
                    'indicators': {
                        'rl_action': action_name,
                        'rl_action_id': int(action),
                        'use_trailing_stop': True
                    }
                }
            
            # HOLD or invalid state
            return None
        
        except Exception as e:
            self.logger.error(f"RL analysis failed: {e}", exc_info=True)
            return None
    
    def update_position(self, position: Optional[Dict]):
        """
        Update internal position state
        
        Args:
            position: Current position dict or None
        """
        self.position = position
