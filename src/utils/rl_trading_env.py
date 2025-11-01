"""
Reinforcement Learning Trading Environment
Gym environment for training RL agents to trade
"""
import numpy as np
import pandas as pd
try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    import gym
    from gym import spaces
from typing import Dict, Optional, Tuple
import logging
from datetime import datetime


class TradingEnv(gym.Env):
    """
    Custom Gym environment for cryptocurrency trading
    
    State Space:
    - Market features (OHLCV, indicators, regime, volume)
    - Position state (open/closed, P&L, duration)
    - Recent performance (win rate, drawdown)
    
    Action Space:
    - 0: HOLD (do nothing)
    - 1: BUY (enter long position)
    - 2: SELL (close position)
    - 3: BUY_LARGE (2x position size)
    - 4: SELL_TRAILING (sell with trailing stop)
    
    Reward:
    - Profit from closed trades
    - Penalty for drawdown
    - Penalty for holding too long
    - Bonus for high Sharpe ratio
    """
    
    metadata = {'render.modes': ['human']}
    
    def __init__(self, df: pd.DataFrame, initial_balance: float = 1000,
                 trading_fee: float = 0.001, max_position_size: float = 100,
                 max_episode_steps: int = 1000):
        """
        Args:
            df: DataFrame with OHLCV + features
            initial_balance: Starting capital
            trading_fee: Trading fee per transaction (0.001 = 0.1%)
            max_position_size: Maximum position size in USD
            max_episode_steps: Max steps per episode
        """
        super(TradingEnv, self).__init__()
        
        self.df = df.reset_index(drop=True)
        self.initial_balance = initial_balance
        self.trading_fee = trading_fee
        self.max_position_size = max_position_size
        self.max_episode_steps = max_episode_steps
        
        self.logger = logging.getLogger(__name__)
        
        # Extract feature columns (all numeric columns except OHLCV basics)
        self.feature_columns = [col for col in df.columns 
                               if col not in ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                               and df[col].dtype in [np.float64, np.float32, np.int64, np.int32]]
        
        self.n_features = len(self.feature_columns)
        
        # Action space: HOLD, BUY, SELL, BUY_LARGE, SELL_TRAILING
        self.action_space = spaces.Discrete(5)
        
        # Observation space: market features + position state + performance metrics
        # Market features: dynamic based on data
        # Position state: [is_open, entry_price_norm, current_pnl_pct, position_duration_norm, position_size_norm]
        # Performance: [total_return, win_rate, sharpe_ratio, max_drawdown]
        obs_dim = self.n_features + 5 + 4
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        
        # Episode state
        self.current_step = 0
        self.balance = initial_balance
        self.position = None  # {entry_price, entry_step, size, fees_paid}
        self.closed_trades = []
        self.equity_curve = []
        self.max_equity = initial_balance
        
        # Performance tracking
        self.total_profit = 0
        self.total_trades = 0
        self.winning_trades = 0
        
    def reset(self, seed=None, options=None):
        """Reset environment to initial state
        
        Args:
            seed: Random seed (Gymnasium compatibility)
            options: Additional options (Gymnasium compatibility)
            
        Returns:
            observation, info (Gymnasium) or just observation (Gym)
        """
        # Set seed if provided
        if seed is not None:
            np.random.seed(seed)
        
        # Random starting point in data (leave room for episode)
        max_start = len(self.df) - self.max_episode_steps - 1
        self.start_step = np.random.randint(0, max(1, max_start))
        self.current_step = self.start_step
        
        # Reset state
        self.balance = self.initial_balance
        self.position = None
        self.closed_trades = []
        self.equity_curve = [self.initial_balance]
        self.max_equity = self.initial_balance
        self.total_profit = 0
        self.total_trades = 0
        self.winning_trades = 0
        
        obs = self._get_observation()
        
        # Return tuple for Gymnasium, just obs for old Gym
        return obs, {}
    
    def _get_observation(self) -> np.ndarray:
        """Construct observation vector"""
        # Market features from current step
        market_features = self.df.loc[self.current_step, self.feature_columns].values.astype(np.float32)
        
        # Replace any NaN with 0
        market_features = np.nan_to_num(market_features, nan=0.0, posinf=1e6, neginf=-1e6)
        
        # Position state
        if self.position:
            current_price = self.df.loc[self.current_step, 'close']
            entry_price = self.position['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            duration_norm = (self.current_step - self.position['entry_step']) / 100  # Normalize duration
            size_norm = self.position['size'] / self.max_position_size
            position_state = np.array([1.0, entry_price / current_price, pnl_pct, duration_norm, size_norm], dtype=np.float32)
        else:
            position_state = np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        
        # Performance metrics
        total_return = (self.balance - self.initial_balance) / self.initial_balance
        win_rate = self.winning_trades / max(1, self.total_trades)
        
        # Sharpe ratio (simplified)
        if len(self.equity_curve) > 10:
            returns = np.diff(self.equity_curve) / self.equity_curve[:-1]
            sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
        else:
            sharpe = 0.0
        
        # Max drawdown
        max_dd = (self.max_equity - self.balance) / self.max_equity if self.max_equity > 0 else 0
        
        performance = np.array([total_return, win_rate, sharpe, max_dd], dtype=np.float32)
        
        # Concatenate all
        obs = np.concatenate([market_features, position_state, performance])
        
        return obs
    
    def step(self, action: int):
        """
        Execute one time step
        
        Args:
            action: Action to take (0-4)
            
        Returns:
            observation, reward, terminated, truncated, info (Gymnasium)
            or observation, reward, done, info (old Gym)
        """
        current_price = self.df.loc[self.current_step, 'close']
        reward = 0.0
        info = {}
        
        # Execute action
        if action == 1 or action == 3:  # BUY or BUY_LARGE
            if not self.position:
                # Open position
                size_multiplier = 2.0 if action == 3 else 1.0
                position_size = min(self.max_position_size * size_multiplier, self.balance * 0.95)
                fees = position_size * self.trading_fee
                
                self.position = {
                    'entry_price': current_price,
                    'entry_step': self.current_step,
                    'size': position_size,
                    'fees_paid': fees
                }
                self.balance -= fees
                info['action'] = 'BUY' if action == 1 else 'BUY_LARGE'
        
        elif action == 2 or action == 4:  # SELL or SELL_TRAILING
            if self.position:
                # Close position
                entry_price = self.position['entry_price']
                position_size = self.position['size']
                quantity = position_size / entry_price
                exit_value = quantity * current_price
                fees = exit_value * self.trading_fee
                
                # Calculate net profit after all fees
                profit = exit_value - position_size - self.position['fees_paid'] - fees
                profit_pct = profit / position_size
                
                self.balance += exit_value - fees
                self.total_profit += profit
                self.total_trades += 1
                
                if profit > 0:
                    self.winning_trades += 1
                
                self.closed_trades.append({
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'duration': self.current_step - self.position['entry_step']
                })
                
                # === FEE & VOLATILITY NORMALIZED REWARD ===
                # Get volatility normalization (ATR%)
                vol_norm = 0.005  # Default 0.5% if unavailable
                if 'atr_pct' in self.df.columns and self.current_step > 0:
                    vol_norm = max(self.df.loc[self.current_step, 'atr_pct'] / 100, 0.001)
                elif 'volatility' in self.df.columns:
                    vol_norm = max(self.df.loc[self.current_step, 'volatility'], 0.001)
                
                # Base reward: net profit normalized by volatility
                base_reward = (profit / position_size) / vol_norm
                reward += base_reward * 100  # Scale for training
                
                # Penalty for weak edges (profit < spread + 2*fees)
                total_fees_pct = (self.position['fees_paid'] + fees) / position_size
                spread_est = 0.0002  # Estimate 2 bps
                min_edge = spread_est + 2 * total_fees_pct
                if profit_pct < min_edge and profit_pct > 0:
                    reward -= 1.0  # Discourage taking tiny profits
                
                # Bonus for maker fills (if we track this)
                # This incentivizes the agent to prefer maker orders
                # (will be implemented when we have maker/taker tracking)
                
                # Extra bonus for quality trades (net profit after fees)
                if profit_pct > 0.005:  # > 0.5% net after fees
                    reward += 2.0  # Reward taking good profits
                
                self.position = None
                info['action'] = 'SELL' if action == 2 else 'SELL_TRAILING'
                info['profit'] = profit
        
        else:  # HOLD
            info['action'] = 'HOLD'
            # Small penalty for inactivity to encourage trading
            if self.total_trades == 0 and self.current_step > 50:
                reward -= 0.01  # Encourage at least some trading
        
        # Update equity curve
        current_equity = self._calculate_equity(current_price)
        self.equity_curve.append(current_equity)
        self.max_equity = max(self.max_equity, current_equity)
        
        # Additional reward shaping
        # Penalty for drawdown
        drawdown = (self.max_equity - current_equity) / self.max_equity
        reward -= drawdown * 5  # Reduced penalty (was 10)
        
        # Penalty for holding losing position too long
        if self.position:
            unrealized_pnl_pct = (current_price - self.position['entry_price']) / self.position['entry_price']
            duration = self.current_step - self.position['entry_step']
            
            if unrealized_pnl_pct < -0.02 and duration > 50:  # Losing >2% for >50 steps
                reward -= 0.1 * duration / 10  # Increasing penalty
            
            # Encourage taking profit on winning positions
            if unrealized_pnl_pct > 0.01 and duration > 20:  # Up 1%+ for >20 steps
                reward += 0.05  # Increased reward for taking profit
            
            # Penalty for not taking profit when well in the green
            if unrealized_pnl_pct > 0.02 and duration > 50:  # Up 2%+ for >50 steps
                reward -= 0.05  # Encourage exit
        
        # Bonus for high Sharpe ratio
        if len(self.equity_curve) > 20:
            returns = np.diff(self.equity_curve[-20:])
            if len(returns) > 0 and np.std(returns) > 0:
                recent_sharpe = np.mean(returns) / np.std(returns)
                reward += recent_sharpe * 0.01
        
        # Move to next step
        self.current_step += 1
        
        # Check if episode is done
        terminated = False  # Episode ended naturally
        truncated = False   # Episode cut short (time limit)
        
        if self.current_step >= min(self.start_step + self.max_episode_steps, len(self.df) - 1):
            truncated = True
            # Force close position at end
            if self.position:
                result = self.step(2)  # Force sell
                close_reward = result[1] if len(result) >= 2 else 0
                reward += close_reward
        
        # Check if bankrupt
        if self.balance < self.initial_balance * 0.1:
            terminated = True
            reward -= 10  # Large penalty for losing too much
        
        # Get next observation
        obs = self._get_observation()
        
        # Info dict
        info.update({
            'balance': self.balance,
            'equity': current_equity,
            'total_trades': self.total_trades,
            'win_rate': self.winning_trades / max(1, self.total_trades),
            'total_profit': self.total_profit
        })
        
        # Return 5-tuple for Gymnasium (stable-baselines3 2.2+ uses this)
        return obs, reward, terminated, truncated, info
    
    def _calculate_equity(self, current_price: float) -> float:
        """Calculate current total equity (balance + unrealized P&L)"""
        equity = self.balance
        
        if self.position:
            entry_price = self.position['entry_price']
            position_size = self.position['size']
            quantity = position_size / entry_price
            current_value = quantity * current_price
            equity += current_value - self.position['fees_paid']
        
        return equity
    
    def render(self, mode='human'):
        """Render environment state"""
        current_price = self.df.loc[self.current_step, 'close']
        equity = self._calculate_equity(current_price)
        
        print(f"Step: {self.current_step - self.start_step}/{self.max_episode_steps}")
        print(f"Price: ${current_price:.2f}")
        print(f"Balance: ${self.balance:.2f}")
        print(f"Equity: ${equity:.2f}")
        print(f"Total Profit: ${self.total_profit:.2f} ({self.total_profit/self.initial_balance*100:.2f}%)")
        print(f"Trades: {self.total_trades}, Win Rate: {self.winning_trades/max(1,self.total_trades)*100:.1f}%")
        
        if self.position:
            unrealized_pnl = (current_price - self.position['entry_price']) / self.position['entry_price'] * 100
            print(f"Position: LONG @ ${self.position['entry_price']:.2f}, P&L: {unrealized_pnl:+.2f}%")
        else:
            print("Position: NONE")
        
        print("-" * 50)
    
    def get_episode_stats(self) -> Dict:
        """Get statistics for completed episode"""
        final_equity = self._calculate_equity(self.df.loc[self.current_step, 'close'])
        total_return = (final_equity - self.initial_balance) / self.initial_balance
        
        # Sharpe ratio
        if len(self.equity_curve) > 2:
            returns = np.diff(self.equity_curve) / self.equity_curve[:-1]
            sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Max drawdown
        max_dd = 0
        peak = self.equity_curve[0]
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        
        # Average trade stats
        if self.closed_trades:
            avg_profit = np.mean([t['profit'] for t in self.closed_trades])
            avg_profit_pct = np.mean([t['profit_pct'] for t in self.closed_trades])
            avg_duration = np.mean([t['duration'] for t in self.closed_trades])
        else:
            avg_profit = 0
            avg_profit_pct = 0
            avg_duration = 0
        
        return {
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': self.winning_trades / max(1, self.total_trades),
            'avg_profit': avg_profit,
            'avg_profit_pct': avg_profit_pct * 100,
            'avg_trade_duration': avg_duration,
            'final_balance': self.balance,
            'final_equity': final_equity
        }
