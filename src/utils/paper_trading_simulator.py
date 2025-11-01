"""
Paper Trading Simulator for Mean Reversion Strategy

Simulates live trading without real money, tracking:
- Virtual balance and positions
- Transaction costs and fees
- Performance metrics
- Risk management
"""
import logging
import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from binance.client import Client
import joblib
import json
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from config.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PaperTradingSimulator:
    """Simulates live trading for strategy validation"""

    def __init__(self, symbol: str, interval: str, initial_balance: float = 1000.0):
        self.symbol = symbol
        self.interval = interval
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.position = None
        self.trades = []
        self.equity_curve = [initial_balance]

        # Load trained model
        self.model = self._load_model()

        # Initialize Binance client
        if config.trading_mode == 'testnet':
            self.client = Client(config.api_key, config.api_secret, testnet=True)
        else:
            self.client = Client(config.api_key, config.api_secret)

        # Trading parameters
        self.maker_fee = 0.001  # 0.1% maker fee
        self.taker_fee = 0.001  # 0.1% taker fee
        self.slippage = 0.0005  # 0.05% slippage

        logger.info(f"Initialized paper trading simulator: {symbol} {interval}")
        logger.info(f"Initial balance: ${initial_balance:.2f}")

    def _load_model(self):
        """Load trained mean reversion model"""
        model_dir = Path('models/mean_reversion')
        model_file = model_dir / f"{self.symbol}_{self.interval}_mean_reversion.joblib"

        if not model_file.exists():
            raise FileNotFoundError(f"Model not found: {model_file}")

        model = joblib.load(model_file)
        logger.info(f"Loaded model: {model_file}")
        return model

    def _calculate_features(self, df: pd.DataFrame) -> pd.Series:
        """Calculate mean reversion features"""
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # Bollinger Bands
        sma_20 = df['close'].rolling(20).mean()
        std_20 = df['close'].rolling(20).std()
        bb_upper = sma_20 + (2 * std_20)
        bb_lower = sma_20 - (2 * std_20)
        bb_position = (df['close'] - bb_lower) / (bb_upper - bb_lower)

        # Volume
        volume_sma = df['volume'].rolling(20).mean()
        volume_ratio = df['volume'] / volume_sma

        # MACD
        ema_12 = df['close'].ewm(span=12).mean()
        ema_26 = df['close'].ewm(span=26).mean()
        macd = ema_12 - ema_26
        macd_signal = macd.ewm(span=9).mean()
        macd_hist = macd - macd_signal

        # ATR (volatility)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_pct = atr / df['close']

        # Price momentum
        returns_1 = df['close'].pct_change(1)
        returns_5 = df['close'].pct_change(5)

        # Support/Resistance context
        recent_high = df['high'].rolling(20).max()
        recent_low = df['low'].rolling(20).min()
        price_range_position = (df['close'] - recent_low) / (recent_high - recent_low)
        distance_to_high = (recent_high - df['close']) / df['close']
        distance_to_low = (df['close'] - recent_low) / df['close']

        # Build feature vector (last row)
        features = pd.Series({
            'rsi': rsi.iloc[-1],
            'rsi_momentum': rsi.diff(1).iloc[-1],
            'bb_position': bb_position.iloc[-1],
            'bb_width': ((bb_upper - bb_lower) / sma_20).iloc[-1],
            'volume_ratio': volume_ratio.iloc[-1],
            'macd_hist': macd_hist.iloc[-1],
            'macd_hist_change': macd_hist.diff(1).iloc[-1],
            'atr_pct': atr_pct.iloc[-1],
            'returns_1': returns_1.iloc[-1],
            'returns_5': returns_5.iloc[-1],
            'price_range_position': price_range_position.iloc[-1],
            'distance_to_high': distance_to_high.iloc[-1],
            'distance_to_low': distance_to_low.iloc[-1],
        })

        return features

    def _apply_fees_and_slippage(self, price: float, side: str) -> float:
        """Apply trading fees and slippage"""
        # Apply slippage
        if side == 'BUY':
            price *= (1 + self.slippage)
        else:  # SELL
            price *= (1 - self.slippage)

        # Apply fees (using maker fee for simplicity)
        fee = price * self.maker_fee
        return price, fee

    def _execute_trade(self, side: str, price: float, timestamp: pd.Timestamp):
        """Execute a simulated trade"""
        price_with_fees, fee = self._apply_fees_and_slippage(price, side)

        if side == 'BUY':
            if self.position is not None:
                logger.warning("Already in position, skipping BUY")
                return

            # Calculate position size (use full balance for simplicity)
            position_size = self.balance / price_with_fees

            self.position = {
                'entry_price': price_with_fees,
                'entry_time': timestamp,
                'size': position_size,
                'fee': fee
            }

            self.balance -= (position_size * price_with_fees)
            logger.info(f"PAPER BUY: {position_size:.6f} @ ${price_with_fees:.4f} (fee: ${fee:.4f})")

        else:  # SELL
            if self.position is None:
                logger.warning("No position to sell, skipping SELL")
                return

            # Calculate exit value
            exit_value = self.position['size'] * price_with_fees
            pnl = exit_value - (self.position['size'] * self.position['entry_price'])

            # Record trade
            trade = {
                'entry_time': self.position['entry_time'],
                'exit_time': timestamp,
                'entry_price': self.position['entry_price'],
                'exit_price': price_with_fees,
                'size': self.position['size'],
                'pnl': pnl,
                'entry_fee': self.position['fee'],
                'exit_fee': fee,
                'total_fees': self.position['fee'] + fee
            }

            self.trades.append(trade)
            self.balance += exit_value

            logger.info(f"PAPER SELL: {self.position['size']:.6f} @ ${price_with_fees:.4f}, PnL: ${pnl:.4f} (fee: ${fee:.4f})")

            self.position = None

        self.equity_curve.append(self.balance)

    async def run_simulation(self, duration_hours: int = 24):
        """Run paper trading simulation"""
        logger.info(f"Starting paper trading simulation for {duration_hours} hours")

        end_time = datetime.now() + timedelta(hours=duration_hours)

        while datetime.now() < end_time:
            try:
                # Get latest market data
                klines = self.client.get_klines(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=100
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

                # Calculate features
                features = self._calculate_features(df)

                if features.isnull().any():
                    await asyncio.sleep(60)  # Wait before next iteration
                    continue

                current_price = float(df['close'].iloc[-1])
                current_time = df['timestamp'].iloc[-1]

                rsi = features['rsi']
                bb_position = features['bb_position']

                # Check for extreme conditions
                is_oversold = rsi < 30 and bb_position < 0.2
                is_overbought = rsi > 70 and bb_position > 0.8

                # ML prediction
                features_array = features.values.reshape(1, -1)
                prediction = self.model.predict(features_array)[0]

                # Trading logic
                if prediction == 1:  # ML predicts successful bounce
                    if is_oversold and self.position is None:
                        # BUY signal
                        self._execute_trade('BUY', current_price, current_time)

                    elif is_overbought and self.position is not None:
                        # SELL signal (take profit at overbought)
                        self._execute_trade('SELL', current_price, current_time)

                # Exit if back to mean
                if self.position is not None and 0.4 < bb_position < 0.6:
                    self._execute_trade('SELL', current_price, current_time)

                # Log current status
                logger.info(f"Balance: ${self.balance:.2f}, Position: {self.position is not None}")

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Simulation error: {e}", exc_info=True)
                await asyncio.sleep(60)

        # Final report
        self._generate_report()

    def _generate_report(self):
        """Generate simulation report"""
        if not self.trades:
            logger.info("No trades executed during simulation")
            return

        trades_df = pd.DataFrame(self.trades)

        # Basic metrics
        total_trades = len(trades_df)
        winning_trades = (trades_df['pnl'] > 0).sum()
        win_rate = winning_trades / total_trades
        total_pnl = trades_df['pnl'].sum()
        total_fees = trades_df['total_fees'].sum()
        net_pnl = total_pnl - total_fees

        avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if (trades_df['pnl'] < 0).any() else 0

        # Performance metrics
        total_return = (self.balance - self.initial_balance) / self.initial_balance

        # Sharpe ratio
        if len(self.equity_curve) > 1:
            returns = pd.Series(self.equity_curve).pct_change().dropna()
            if returns.std() > 0:
                sharpe_ratio = returns.mean() / returns.std() * np.sqrt(365 * 24)  # Hourly to annual
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        # Max drawdown
        cumulative = pd.Series(self.equity_curve)
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()

        logger.info("\n" + "="*60)
        logger.info("PAPER TRADING SIMULATION RESULTS")
        logger.info("="*60)
        logger.info(f"Symbol: {self.symbol}")
        logger.info(f"Timeframe: {self.interval}")
        logger.info(f"Initial Balance: ${self.initial_balance:.2f}")
        logger.info(f"Final Balance: ${self.balance:.2f}")
        logger.info(f"Total Return: {total_return:.2%}")
        logger.info(f"Total Trades: {total_trades}")
        logger.info(f"Win Rate: {win_rate:.1%}")
        logger.info(f"Average Win: ${avg_win:.2f}")
        logger.info(f"Average Loss: ${avg_loss:.2f}")
        logger.info(f"Total PnL: ${total_pnl:.2f}")
        logger.info(f"Total Fees: ${total_fees:.2f}")
        logger.info(f"Net PnL: ${net_pnl:.2f}")
        logger.info(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        logger.info(f"Max Drawdown: {max_drawdown:.2%}")
        logger.info("="*60)


async def main():
    """Main function for paper trading simulation"""
    import argparse

    parser = argparse.ArgumentParser(description='Paper Trading Simulator')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--interval', type=str, default='1h', help='Timeframe')
    parser.add_argument('--duration-hours', type=int, default=24, help='Simulation duration in hours')
    parser.add_argument('--initial-balance', type=float, default=1000.0, help='Initial balance')

    args = parser.parse_args()

    simulator = PaperTradingSimulator(
        symbol=args.symbol,
        interval=args.interval,
        initial_balance=args.initial_balance
    )

    await simulator.run_simulation(duration_hours=args.duration_hours)


if __name__ == '__main__':
    asyncio.run(main())