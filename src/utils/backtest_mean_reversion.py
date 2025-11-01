"""
Backtest Mean Reversion Strategy

Evaluates strategy performance with key metrics:
- Sharpe ratio
- Win rate
- Maximum drawdown
- Profit/loss ratio
- Total return
"""
import argparse
import logging
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


def fetch_klines(client: Client, symbol: str, interval: str, lookback_days: int):
    """Fetch historical klines"""
    start_time = datetime.now() - timedelta(days=lookback_days)
    start_str = start_time.strftime('%Y-%m-%d')

    logger.info(f"Fetching klines for {symbol} {interval} from {start_str}")

    klines = client.get_historical_klines(
        symbol,
        interval,
        start_str
    )

    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col])

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

    logger.info(f"Fetched {len(df)} candles")
    return df


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate mean reversion features"""
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi_momentum'] = df['rsi'].diff(1)

    # Bollinger Bands
    sma_20 = df['close'].rolling(20).mean()
    std_20 = df['close'].rolling(20).std()
    bb_upper = sma_20 + (2 * std_20)
    bb_lower = sma_20 - (2 * std_20)
    df['bb_position'] = (df['close'] - bb_lower) / (bb_upper - bb_lower)
    df['bb_width'] = (bb_upper - bb_lower) / sma_20

    # Volume
    volume_sma = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / volume_sma

    # MACD
    ema_12 = df['close'].ewm(span=12).mean()
    ema_26 = df['close'].ewm(span=26).mean()
    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9).mean()
    df['macd_hist'] = macd - macd_signal
    df['macd_hist_change'] = df['macd_hist'].diff(1)

    # ATR (volatility)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    df['atr_pct'] = atr / df['close']

    # Price momentum
    df['returns_1'] = df['close'].pct_change(1)
    df['returns_5'] = df['close'].pct_change(5)

    # Support/Resistance context
    recent_high = df['high'].rolling(20).max()
    recent_low = df['low'].rolling(20).min()
    df['price_range_position'] = (df['close'] - recent_low) / (recent_high - recent_low)
    df['distance_to_high'] = (recent_high - df['close']) / df['close']
    df['distance_to_low'] = (df['close'] - recent_low) / df['close']

    return df


def backtest_strategy(symbol: str, interval: str, lookback_days: int, initial_balance: float = 1000.0):
    """Backtest mean reversion strategy"""
    # Initialize Binance client
    if config.trading_mode == 'testnet':
        client = Client(config.api_key, config.api_secret, testnet=True)
    else:
        client = Client(config.api_key, config.api_secret)

    # Load trained model
    model_dir = Path('models/mean_reversion')
    model_file = model_dir / f"{symbol}_{interval}_mean_reversion.joblib"

    if not model_file.exists():
        logger.error(f"No trained model found for {symbol} {interval}")
        return

    model = joblib.load(model_file)
    logger.info(f"Loaded model: {model_file}")

    # Fetch data
    df = fetch_klines(client, symbol, interval, lookback_days)

    # Calculate features
    logger.info("Calculating features...")
    df = calculate_features(df)

    # Drop rows with NaN
    df = df.dropna().reset_index(drop=True)

    if len(df) < 100:
        logger.error("Not enough data for backtesting")
        return

    # Backtest parameters
    balance = initial_balance
    position = None
    trades = []
    equity_curve = [initial_balance]

    logger.info("Starting backtest...")

    for i in range(len(df)):
        if i < 50:  # Skip initial rows for feature calculation
            continue

        # Get current data window
        window_df = df.iloc[max(0, i-100):i+1].copy()

        # Calculate features for current row
        features = pd.Series({
            'rsi': window_df['rsi'].iloc[-1],
            'rsi_momentum': window_df['rsi_momentum'].iloc[-1],
            'bb_position': window_df['bb_position'].iloc[-1],
            'bb_width': window_df['bb_width'].iloc[-1],
            'volume_ratio': window_df['volume_ratio'].iloc[-1],
            'macd_hist': window_df['macd_hist'].iloc[-1],
            'macd_hist_change': window_df['macd_hist_change'].iloc[-1],
            'atr_pct': window_df['atr_pct'].iloc[-1],
            'returns_1': window_df['returns_1'].iloc[-1],
            'returns_5': window_df['returns_5'].iloc[-1],
            'price_range_position': window_df['price_range_position'].iloc[-1],
            'distance_to_high': window_df['distance_to_high'].iloc[-1],
            'distance_to_low': window_df['distance_to_low'].iloc[-1],
        })

        if features.isnull().any():
            continue

        current_price = float(window_df['close'].iloc[-1])
        rsi = features['rsi']
        bb_position = features['bb_position']

        # Check for extreme conditions
        is_oversold = rsi < 30 and bb_position < 0.2
        is_overbought = rsi > 70 and bb_position > 0.8

        # ML prediction
        features_array = features.values.reshape(1, -1)
        prediction = model.predict(features_array)[0]

        # Trading logic
        if prediction == 1:  # ML predicts successful bounce
            if is_oversold and position is None:
                # BUY signal
                position = {
                    'entry_price': current_price,
                    'entry_time': window_df['timestamp'].iloc[-1],
                    'type': 'long'
                }
                logger.info(f"BUY at {current_price:.4f} on {window_df['timestamp'].iloc[-1]}")

            elif is_overbought and position is not None and position['type'] == 'long':
                # SELL signal (take profit at overbought)
                exit_price = current_price
                pnl = (exit_price - position['entry_price']) / position['entry_price']
                balance *= (1 + pnl)

                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': window_df['timestamp'].iloc[-1],
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'type': 'long'
                })

                logger.info(f"SELL at {exit_price:.4f} on {window_df['timestamp'].iloc[-1]}, PnL: {pnl:.2%}")
                position = None

        # Exit if back to mean
        if position is not None and 0.4 < bb_position < 0.6:
            exit_price = current_price
            pnl = (exit_price - position['entry_price']) / position['entry_price']
            balance *= (1 + pnl)

            trades.append({
                'entry_time': position['entry_time'],
                'exit_time': window_df['timestamp'].iloc[-1],
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'pnl': pnl,
                'type': 'long'
            })

            logger.info(f"EXIT at mean {exit_price:.4f} on {window_df['timestamp'].iloc[-1]}, PnL: {pnl:.2%}")
            position = None

        equity_curve.append(balance)

    # Calculate performance metrics
    if trades:
        trades_df = pd.DataFrame(trades)
        equity_curve = equity_curve[:len(trades_df)+1]  # Trim to match trades

        # Basic metrics
        total_return = (balance - initial_balance) / initial_balance
        win_rate = (trades_df['pnl'] > 0).mean()
        avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean()
        avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean()
        profit_factor = abs(trades_df[trades_df['pnl'] > 0]['pnl'].sum() / trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if (trades_df['pnl'] < 0).any() else float('inf')

        # Sharpe ratio (assuming daily returns, adjust for timeframe)
        returns = pd.Series(equity_curve).pct_change().dropna()
        if len(returns) > 1:
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(365)  # Annualized
        else:
            sharpe_ratio = 0

        # Maximum drawdown
        cumulative = pd.Series(equity_curve)
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()

        # Print results
        logger.info("\n" + "="*50)
        logger.info("BACKTEST RESULTS")
        logger.info("="*50)
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Timeframe: {interval}")
        logger.info(f"Period: {lookback_days} days")
        logger.info(f"Total Trades: {len(trades)}")
        logger.info(f"Win Rate: {win_rate:.1%}")
        logger.info(f"Average Win: {avg_win:.2%}")
        logger.info(f"Average Loss: {avg_loss:.2%}")
        logger.info(f"Profit Factor: {profit_factor:.2f}")
        logger.info(f"Total Return: {total_return:.2%}")
        logger.info(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        logger.info(f"Max Drawdown: {max_drawdown:.2%}")
        logger.info(f"Final Balance: ${balance:.2f}")
        logger.info("="*50)

        return {
            'total_trades': len(trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_return': total_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'final_balance': balance,
            'trades': trades
        }
    else:
        logger.warning("No trades executed during backtest")
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backtest Mean Reversion Strategy')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--interval', type=str, default='1h', help='Timeframe')
    parser.add_argument('--lookback-days', type=int, default=180, help='Days of historical data')
    parser.add_argument('--initial-balance', type=float, default=1000.0, help='Initial balance')

    args = parser.parse_args()

    backtest_strategy(args.symbol, args.interval, args.lookback_days, args.initial_balance)