"""
Market-Aware Feature Engineering
Adds contextual features that help ML "see" the market, not just indicators
"""
import pandas as pd
import numpy as np
from binance.client import Client


def add_market_aware_features(df: pd.DataFrame, client: Client, symbol: str, interval: str) -> pd.DataFrame:
    """
    Add market-aware features to enhance ML understanding of context
    
    Args:
        df: DataFrame with OHLCV data
        client: Binance client for fetching higher timeframe data
        symbol: Trading pair
        interval: Current timeframe (e.g., '5m')
    
    Returns:
        DataFrame with additional market-aware features
    """
    
    # === 1. MULTI-TIMEFRAME ALIGNMENT ===
    # Fetch 1h data for higher timeframe trend
    if interval in ['5m', '15m']:
        df = add_higher_timeframe_trend(df, client, symbol, interval)
    
    # === 2. VOLUME MICROSTRUCTURE ===
    df = add_volume_features(df)
    
    # === 3. MARKET REGIME DETECTION ===
    df = add_regime_features(df)
    
    # === 4. SUPPORT/RESISTANCE FROM VOLUME ===
    df = add_volume_profile_levels(df)
    
    return df


def add_higher_timeframe_trend(df: pd.DataFrame, client: Client, symbol: str, interval: str) -> pd.DataFrame:
    """Add 1h trend alignment for 5m/15m strategies"""
    try:
        # Fetch 1h data
        h1_klines = client.get_klines(
            symbol=symbol,
            interval='1h',
            limit=200
        )
        
        h1_df = pd.DataFrame(h1_klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        h1_df['close'] = pd.to_numeric(h1_df['close'])
        h1_df['timestamp'] = pd.to_datetime(h1_df['timestamp'], unit='ms')
        
        # Calculate 1h EMAs
        h1_df['ema_20_1h'] = h1_df['close'].ewm(span=20).mean()
        h1_df['ema_50_1h'] = h1_df['close'].ewm(span=50).mean()
        
        # 1h trend direction
        h1_df['h1_trend'] = np.where(h1_df['ema_20_1h'] > h1_df['ema_50_1h'], 1, -1)
        h1_df['h1_trend_strength'] = abs(h1_df['ema_20_1h'] - h1_df['ema_50_1h']) / h1_df['close']
        
        # Merge back to 5m/15m data (forward fill for alignment)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = pd.merge_asof(
            df.sort_values('timestamp'),
            h1_df[['timestamp', 'h1_trend', 'h1_trend_strength', 'ema_20_1h', 'ema_50_1h']].sort_values('timestamp'),
            on='timestamp',
            direction='backward'
        )
        
        # Trend confluence: 5m signal + 1h trend alignment
        df['trend_confluence'] = 0
        if 'ema_20' in df.columns and 'ema_50' in df.columns:
            df['trend_confluence'] = np.where(
                (df['ema_20'] > df['ema_50']) & (df['h1_trend'] == 1), 1,  # Both bullish
                np.where(
                    (df['ema_20'] < df['ema_50']) & (df['h1_trend'] == -1), -1,  # Both bearish
                    0  # Divergence
                )
            )
        
    except Exception as e:
        print(f"Warning: Could not fetch 1h data for multi-timeframe features: {e}")
        df['h1_trend'] = 0
        df['h1_trend_strength'] = 0
        df['trend_confluence'] = 0
    
    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add volume microstructure features"""
    
    # VWAP (Volume Weighted Average Price)
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_dist'] = (df['close'] - df['vwap']) / df['close']
    
    # Volume momentum
    df['vol_ma_20'] = df['volume'].rolling(20).mean()
    df['vol_surge'] = df['volume'] / df['vol_ma_20']
    
    # Buying vs selling pressure (using taker buy volume)
    if 'taker_buy_base' in df.columns and 'taker_buy_quote' in df.columns:
        df['buy_volume'] = pd.to_numeric(df['taker_buy_base'], errors='coerce')
        df['sell_volume'] = df['volume'] - df['buy_volume']
        df['buy_sell_ratio'] = df['buy_volume'] / (df['sell_volume'] + 1e-10)
        df['net_volume'] = df['buy_volume'] - df['sell_volume']
        
        # Smart money flow (volume-weighted price change)
        df['price_change'] = df['close'].pct_change()
        df['money_flow'] = df['price_change'] * df['volume'] * np.sign(df['net_volume'])
        df['money_flow_20'] = df['money_flow'].rolling(20).sum()
    else:
        df['buy_sell_ratio'] = 1.0
        df['money_flow_20'] = 0.0
    
    # Volume profile: find high-volume price levels (support/resistance)
    df['volume_percentile'] = df['volume'].rolling(100).apply(
        lambda x: (x.iloc[-1] / x.quantile(0.9)) if len(x) > 0 else 1.0
    )
    
    return df


def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime: trending, ranging, or volatile"""
    
    # ADX (trend strength indicator)
    def calculate_adx(df, period=14):
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        
        # Directional Movement
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / (atr + 1e-10)
        minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / (atr + 1e-10)
        
        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(period).mean()
        
        return adx, plus_di, minus_di
    
    df['adx'], df['plus_di'], df['minus_di'] = calculate_adx(df)
    
    # Market regime classification
    df['regime_trending'] = np.where(df['adx'] > 25, 1, 0)
    df['regime_ranging'] = np.where((df['adx'] < 20), 1, 0)
    
    # Volatility regime
    df['volatility'] = df['close'].pct_change().rolling(20).std()
    df['volatility_percentile'] = df['volatility'].rolling(100).apply(
        lambda x: (x.iloc[-1] / x.quantile(0.75)) if len(x) > 0 else 1.0
    )
    df['regime_volatile'] = np.where(df['volatility_percentile'] > 1.5, 1, 0)
    
    # Trend direction within regime
    df['regime_direction'] = np.where(
        df['plus_di'] > df['minus_di'], 1, -1
    )
    
    return df


def add_volume_profile_levels(df: pd.DataFrame, lookback=100) -> pd.DataFrame:
    """Add support/resistance levels based on volume profile"""
    
    def find_volume_levels(prices, volumes, n_levels=3):
        """Find price levels with highest volume (support/resistance)"""
        if len(prices) < 10:
            return [0] * n_levels
        
        # Create price bins
        price_min, price_max = prices.min(), prices.max()
        bins = np.linspace(price_min, price_max, 20)
        
        # Sum volume in each bin
        volume_profile = []
        for i in range(len(bins) - 1):
            mask = (prices >= bins[i]) & (prices < bins[i+1])
            volume_profile.append(volumes[mask].sum())
        
        # Find top N volume levels
        top_indices = np.argsort(volume_profile)[-n_levels:]
        levels = [(bins[i] + bins[i+1]) / 2 for i in top_indices]
        
        return sorted(levels)
    
    # Calculate support/resistance levels over rolling window
    df['support_1'] = 0.0
    df['resistance_1'] = 0.0
    df['sr_distance'] = 0.0
    
    for i in range(lookback, len(df)):
        window_prices = df['close'].iloc[i-lookback:i]
        window_volumes = df['volume'].iloc[i-lookback:i]
        current_price = df['close'].iloc[i]
        
        levels = find_volume_levels(window_prices.values, window_volumes.values, n_levels=5)
        
        # Find nearest support (below price) and resistance (above price)
        supports = [l for l in levels if l < current_price]
        resistances = [l for l in levels if l > current_price]
        
        if supports:
            df.loc[df.index[i], 'support_1'] = max(supports)
        if resistances:
            df.loc[df.index[i], 'resistance_1'] = min(resistances)
        
        # Distance to nearest level (normalized)
        if supports and resistances:
            dist_support = (current_price - max(supports)) / current_price
            dist_resistance = (min(resistances) - current_price) / current_price
            df.loc[df.index[i], 'sr_distance'] = min(dist_support, dist_resistance)
    
    return df
