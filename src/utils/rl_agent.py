"""
RL Trading Agent
Train and deploy RL agents using stable-baselines3
"""
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict
import joblib

# Try to import stable-baselines3, provide fallback if not installed
try:
    from stable_baselines3 import PPO, A2C
    from stable_baselines3.common.vec_env import DummyVecEnv
    from stable_baselines3.common.callbacks import BaseCallback
    SB3_AVAILABLE = True
except ImportError:
    SB3_AVAILABLE = False
    logging.warning("stable-baselines3 not installed. Run: pip install stable-baselines3")

from utils.rl_trading_env import TradingEnv


class TradingCallback(BaseCallback):
    """
    Callback for logging training progress
    """
    def __init__(self, log_freq: int = 1000, verbose: int = 0):
        super(TradingCallback, self).__init__(verbose)
        self.log_freq = log_freq
        self.episode_rewards = []
        self.episode_returns = []
        
    def _on_step(self) -> bool:
        # Log every N steps
        if self.num_timesteps % self.log_freq == 0:
            # Get episode stats from info
            if len(self.locals.get('infos', [])) > 0:
                info = self.locals['infos'][0]
                if 'episode' in info:
                    self.logger.record('rollout/ep_rew_mean', info['episode']['r'])
                    self.logger.record('rollout/ep_len_mean', info['episode']['l'])
        
        return True


class RLTradingAgent:
    """
    Reinforcement Learning trading agent
    
    Uses PPO (Proximal Policy Optimization) to learn trading strategies
    """
    
    def __init__(self, symbol: str = 'BTCUSDT', timeframe: str = '5m',
                 model_dir: str = 'models/rl_agents'):
        """
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            model_dir: Directory to save trained models
        """
        if not SB3_AVAILABLE:
            raise ImportError("stable-baselines3 not installed. Run: pip install stable-baselines3")
        
        self.symbol = symbol
        self.timeframe = timeframe
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        self.agent = None
        self.env = None
        self.training_history = []
    
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare data for RL training
        Ensure all necessary features are present
        
        Args:
            df: Raw OHLCV + features data
            
        Returns:
            Prepared DataFrame
        """
        # Make a copy
        df = df.copy()
        
        # Ensure we have basic features
        required_cols = ['close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Fill NaN values
        df = df.fillna(method='ffill').fillna(method='bfill').fillna(0)
        
        return df
    
    def create_env(self, df: pd.DataFrame, initial_balance: float = 1000,
                   max_episode_steps: int = 1000) -> DummyVecEnv:
        """
        Create training environment
        
        Args:
            df: Prepared trading data
            initial_balance: Starting capital for each episode
            max_episode_steps: Max steps per episode
            
        Returns:
            Vectorized environment
        """
        def make_env():
            return TradingEnv(
                df=df,
                initial_balance=initial_balance,
                trading_fee=0.001,
                max_position_size=initial_balance * 0.2,  # Risk 20% per trade
                max_episode_steps=max_episode_steps
            )
        
        # Wrap in vector environment
        env = DummyVecEnv([make_env])
        self.env = env
        
        return env
    
    def train(self, df: pd.DataFrame, total_timesteps: int = 100000,
              initial_balance: float = 1000, max_episode_steps: int = 500,
              algorithm: str = 'PPO', save_freq: int = 10000):
        """
        Train RL agent
        
        Args:
            df: Trading data with features
            total_timesteps: Total training steps
            initial_balance: Starting balance per episode
            max_episode_steps: Steps per episode
            algorithm: 'PPO' or 'A2C'
            save_freq: Save model every N steps
        """
        self.logger.info(f"Training RL agent on {self.symbol} {self.timeframe}")
        self.logger.info(f"Data shape: {df.shape}, Total timesteps: {total_timesteps}")
        
        # Prepare data
        df_prepared = self.prepare_data(df)
        
        # Create environment
        env = self.create_env(df_prepared, initial_balance, max_episode_steps)
        
        # Create agent with TensorBoard logging
        tensorboard_log = None
        try:
            # Try to set up TensorBoard logging
            import tensorboard
            log_dir = Path(f"logs/rl_tensorboard/{self.symbol}_{self.timeframe}")
            log_dir.mkdir(parents=True, exist_ok=True)
            tensorboard_log = str(log_dir)
            self.logger.info(f"TensorBoard logging enabled: {tensorboard_log}")
        except ImportError:
            self.logger.warning("TensorBoard not available, training without visualization")
        
        if algorithm == 'PPO':
            self.agent = PPO(
                'MlpPolicy',
                env,
                verbose=1,
                learning_rate=3e-4,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                ent_coef=0.05,  # Higher entropy = more exploration (was 0.01)
                tensorboard_log=tensorboard_log
            )
        elif algorithm == 'A2C':
            self.agent = A2C(
                'MlpPolicy',
                env,
                verbose=1,
                learning_rate=7e-4,
                n_steps=5,
                gamma=0.99,
                gae_lambda=1.0,
                ent_coef=0.01,
                tensorboard_log=tensorboard_log
            )
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        
        # Training callback
        callback = TradingCallback(log_freq=1000)
        
        # Train
        self.logger.info("Starting training...")
        self.agent.learn(
            total_timesteps=total_timesteps,
            callback=callback,
            progress_bar=False  # Disable progress bar to avoid tqdm/rich issues
        )
        
        # Save final model
        model_path = self.model_dir / f"{self.symbol}_{self.timeframe}_rl_agent.zip"
        self.agent.save(model_path)
        self.logger.info(f"✅ RL agent saved: {model_path}")
        
        # Evaluate
        self.logger.info("Evaluating trained agent...")
        eval_stats = self.evaluate(df_prepared, n_episodes=10)
        
        # Save metadata
        meta = {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'algorithm': algorithm,
            'total_timesteps': total_timesteps,
            'trained_at': pd.Timestamp.now().isoformat(),
            'data_samples': len(df),
            'evaluation': eval_stats
        }
        
        import json
        with open(model_path.with_suffix('.meta.json'), 'w') as f:
            json.dump(meta, f, indent=2)
        
        self.training_history.append(meta)
        
        return eval_stats
    
    def evaluate(self, df: pd.DataFrame, n_episodes: int = 10,
                 initial_balance: float = 1000) -> Dict:
        """
        Evaluate trained agent
        
        Args:
            df: Test data
            n_episodes: Number of episodes to evaluate
            initial_balance: Starting balance
            
        Returns:
            Evaluation statistics
        """
        if not self.agent:
            raise ValueError("No agent trained yet")
        
        # Prepare data
        df_prepared = self.prepare_data(df)
        
        # Create test environment
        test_env = TradingEnv(
            df=df_prepared,
            initial_balance=initial_balance,
            trading_fee=0.001,
            max_position_size=initial_balance * 0.2,
            max_episode_steps=500
        )
        
        episode_stats = []
        
        for ep in range(n_episodes):
            reset_result = test_env.reset()
            # Handle both Gym (returns obs) and Gymnasium (returns obs, info)
            obs = reset_result[0] if isinstance(reset_result, tuple) else reset_result
            done = False
            
            while not done:
                action, _ = self.agent.predict(obs, deterministic=True)
                step_result = test_env.step(action)
                # Handle both 4-tuple (old Gym) and 5-tuple (Gymnasium)
                if len(step_result) == 5:
                    obs, reward, terminated, truncated, info = step_result
                    done = terminated or truncated
                else:
                    obs, reward, done, info = step_result
            
            stats = test_env.get_episode_stats()
            episode_stats.append(stats)
            
            self.logger.info(
                f"Episode {ep+1}/{n_episodes}: "
                f"Return: {stats['total_return_pct']:.2f}%, "
                f"Sharpe: {stats['sharpe_ratio']:.2f}, "
                f"Trades: {stats['total_trades']}, "
                f"Win Rate: {stats['win_rate']*100:.1f}%"
            )
        
        # Aggregate statistics
        avg_return = np.mean([s['total_return_pct'] for s in episode_stats])
        avg_sharpe = np.mean([s['sharpe_ratio'] for s in episode_stats])
        avg_max_dd = np.mean([s['max_drawdown'] for s in episode_stats])
        avg_win_rate = np.mean([s['win_rate'] for s in episode_stats])
        avg_trades = np.mean([s['total_trades'] for s in episode_stats])
        
        summary = {
            'avg_return_pct': avg_return,
            'avg_sharpe_ratio': avg_sharpe,
            'avg_max_drawdown': avg_max_dd,
            'avg_win_rate': avg_win_rate,
            'avg_trades_per_episode': avg_trades,
            'n_episodes': n_episodes
        }
        
        self.logger.info(
            f"✅ Evaluation Summary:\n"
            f"  Avg Return: {avg_return:.2f}%\n"
            f"  Avg Sharpe: {avg_sharpe:.2f}\n"
            f"  Avg Win Rate: {avg_win_rate*100:.1f}%\n"
            f"  Avg Trades: {avg_trades:.1f}"
        )
        
        return summary
    
    def load(self, model_path: Optional[str] = None):
        """Load trained agent"""
        if model_path is None:
            model_path = self.model_dir / f"{self.symbol}_{self.timeframe}_rl_agent.zip"
        else:
            model_path = Path(model_path)
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        self.agent = PPO.load(model_path)
        self.logger.info(f"Loaded RL agent from {model_path}")
    
    def predict(self, obs: np.ndarray, deterministic: bool = True) -> int:
        """
        Predict action given observation
        
        Args:
            obs: Current observation
            deterministic: Use deterministic policy
            
        Returns:
            Action (0-4)
        """
        if not self.agent:
            raise ValueError("No agent loaded")
        
        action, _ = self.agent.predict(obs, deterministic=deterministic)
        return int(action)
    
    def get_action_name(self, action: int) -> str:
        """Convert action number to name"""
        action_names = {
            0: 'HOLD',
            1: 'BUY',
            2: 'SELL',
            3: 'BUY_LARGE',
            4: 'SELL_TRAILING'
        }
        return action_names.get(action, 'UNKNOWN')


# Training script
def train_rl_agent_for_symbol(symbol: str, timeframe: str = '5m',
                               lookback_days: int = 180,
                               total_timesteps: int = 100000):
    """
    Helper function to train RL agent for a specific symbol
    
    Args:
        symbol: Trading pair
        timeframe: Candle interval
        lookback_days: Days of data to train on
        total_timesteps: Training steps
    """
    from binance.client import Client
    from config.config import Config
    from datetime import datetime, timedelta
    
    logger = logging.getLogger(__name__)
    
    # Load config
    config = Config()
    
    # Initialize Binance client
    if config.trading_mode == "testnet":
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)
    
    # Fetch data
    logger.info(f"Fetching {lookback_days} days of {symbol} {timeframe} data...")
    end_time = datetime.now()
    start_time = end_time - timedelta(days=lookback_days)
    
    klines = client.get_historical_klines(
        symbol=symbol,
        interval=timeframe,
        start_str=str(int(start_time.timestamp() * 1000)),
        end_str=str(int(end_time.timestamp() * 1000))
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
    
    # Add basic features (RL will learn from these)
    df['returns'] = df['close'].pct_change()
    df['sma_10'] = df['close'].rolling(10).mean()
    df['sma_30'] = df['close'].rolling(30).mean()
    df['volume_sma'] = df['volume'].rolling(10).mean()
    df['volatility'] = df['returns'].rolling(20).std()
    
    # Drop NaN
    df = df.dropna()
    
    logger.info(f"Prepared {len(df)} candles for training")
    
    # Create and train agent
    agent = RLTradingAgent(symbol=symbol, timeframe=timeframe)
    eval_stats = agent.train(
        df=df,
        total_timesteps=total_timesteps,
        initial_balance=1000,
        max_episode_steps=500,
        algorithm='PPO'
    )
    
    return agent, eval_stats


if __name__ == '__main__':
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Train agent for BTCUSDT
    agent, stats = train_rl_agent_for_symbol(
        symbol='BTCUSDT',
        timeframe='5m',
        lookback_days=180,
        total_timesteps=50000  # Start small for testing
    )
    
    print("\n" + "="*50)
    print("Training Complete!")
    print("="*50)
    print(f"Avg Return: {stats['avg_return_pct']:.2f}%")
    print(f"Avg Sharpe: {stats['avg_sharpe_ratio']:.2f}")
    print(f"Avg Win Rate: {stats['avg_win_rate']*100:.1f}%")
