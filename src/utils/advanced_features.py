"""
Advanced Feature Engineering for Trading ML Models
Implements 50+ technical indicators and market microstructure features
"""
import numpy as np
import pandas as pd
from typing import Tuple, Optional
import logging


logger = logging.getLogger(__name__)


class AdvancedFeatureEngine:
    """Advanced feature engineering for trading strategies"""
    
    def __init__(self):
        self.feature_names = []
    
    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def _macd(self, series: pd.Series, fast=12, slow=26, signal=9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD, Signal, and Histogram"""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def _bollinger_bands(self, series: pd.Series, period=20, std_dev=2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands"""
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    def _atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
        """Calculate Average True Range"""
        high_low = high - low
        high_close = abs(high - close.shift(1))
        low_close = abs(low - close.shift(1))
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def _stochastic(self, high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> Tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator"""
        lowest_low = low.rolling(period).min()
        highest_high = high.rolling(period).max()
        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
        d = k.rolling(3).mean()
        return k, d
    
    def _adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
        """Calculate Average Directional Index (trend strength)"""
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = self._atr(high, low, close, period=1)
        atr = tr.rolling(period).mean()
        
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(period).mean()
        
        return adx
    
    def _obv(self, close: pd.Series, volume: pd.Series) -> pd.Series:
        """Calculate On-Balance Volume"""
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        return obv
    
    def _vwap(self, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """Calculate Volume Weighted Average Price"""
        typical_price = (high + low + close) / 3
        return (typical_price * volume).cumsum() / volume.cumsum()
    
    def _ichimoku(self, high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
        """Calculate Ichimoku Cloud components"""
        # Tenkan-sen (Conversion Line): 9-period
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        
        # Kijun-sen (Base Line): 26-period
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        
        # Senkou Span A (Leading Span A)
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        
        # Senkou Span B (Leading Span B): 52-period
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        
        # Chikou Span (Lagging Span)
        chikou = close.shift(-26)
        
        return {
            'tenkan': tenkan,
            'kijun': kijun,
            'senkou_a': senkou_a,
            'senkou_b': senkou_b,
            'chikou': chikou
        }
    
    def _market_regime(self, close: pd.Series, volume: pd.Series) -> pd.Series:
        """Detect market regime: trending vs ranging"""
        # ADX-based regime detection
        returns = close.pct_change()
        volatility = returns.rolling(20).std()
        
        # Trending: high volatility + directional movement
        # Ranging: low volatility + choppy movement
        
        sma_short = close.rolling(10).mean()
        sma_long = close.rolling(50).mean()
        trend_strength = abs(sma_short - sma_long) / sma_long
        
        # 0 = ranging, 1 = trending
        regime = (trend_strength > trend_strength.rolling(50).mean()).astype(int)
        return regime
    
    def _hurst_exponent(self, series: pd.Series, lags=20) -> float:
        """Calculate Hurst Exponent (mean reversion vs trending)"""
        # H < 0.5: mean reverting
        # H = 0.5: random walk
        # H > 0.5: trending
        
        if len(series) < lags * 2:
            return 0.5
        
        lags_range = range(2, lags)
        tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags_range]
        
        try:
            # Add small epsilon to avoid log(0)
            tau_safe = [t + 1e-10 for t in tau]
            poly = np.polyfit(np.log(lags_range), np.log(tau_safe), 1)
            return poly[0]
        except:
            return 0.5
    
    def _volume_profile(self, close: pd.Series, volume: pd.Series, bins=10) -> dict:
        """Calculate volume profile features"""
        # Volume at different price levels
        close_normalized = (close - close.min()) / (close.max() - close.min() + 1e-10)
        
        volume_ma = volume.rolling(20).mean()
        volume_ratio = volume / (volume_ma + 1e-10)
        
        return {
            'volume_ratio': volume_ratio,
            'volume_trend': volume.pct_change(5),
            'volume_volatility': volume.rolling(20).std() / (volume.rolling(20).mean() + 1e-10)
        }
    
    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build comprehensive feature set from OHLCV data
        
        Args:
            df: DataFrame with columns: open, high, low, close, volume
            
        Returns:
            DataFrame with 50+ engineered features
        """
        if len(df) < 100:
            logger.warning(f"Insufficient data: {len(df)} rows")
            return pd.DataFrame()
        
        features = pd.DataFrame(index=df.index)
        
        # Price-based features
        close = df['close']
        high = df['high']
        low = df['low']
        open_ = df['open']
        volume = df['volume']
        
        # === TREND INDICATORS ===
        # EMAs
        features['ema_5'] = close.ewm(span=5, adjust=False).mean()
        features['ema_8'] = close.ewm(span=8, adjust=False).mean()
        features['ema_13'] = close.ewm(span=13, adjust=False).mean()
        features['ema_21'] = close.ewm(span=21, adjust=False).mean()
        features['ema_50'] = close.ewm(span=50, adjust=False).mean()
        
        # SMAs
        features['sma_10'] = close.rolling(10).mean()
        features['sma_20'] = close.rolling(20).mean()
        features['sma_50'] = close.rolling(50).mean()
        
        # EMA crosses (normalized)
        features['ema_cross_5_8'] = (features['ema_5'] - features['ema_8']) / close
        features['ema_cross_8_21'] = (features['ema_8'] - features['ema_21']) / close
        features['ema_cross_13_50'] = (features['ema_13'] - features['ema_50']) / close
        
        # Cross momentum
        features['ema_cross_momentum'] = features['ema_cross_5_8'].diff()
        
        # === MACD ===
        macd, signal, hist = self._macd(close)
        features['macd'] = macd / close
        features['macd_signal'] = signal / close
        features['macd_hist'] = hist / close
        features['macd_hist_diff'] = hist.diff()
        
        # === BOLLINGER BANDS ===
        bb_upper, bb_mid, bb_lower = self._bollinger_bands(close)
        features['bb_position'] = (close - bb_lower) / (bb_upper - bb_lower + 1e-10)
        features['bb_width'] = (bb_upper - bb_lower) / bb_mid
        features['bb_upper_dist'] = (bb_upper - close) / close
        features['bb_lower_dist'] = (close - bb_lower) / close
        
        # === MOMENTUM INDICATORS ===
        features['rsi_14'] = self._rsi(close, 14)
        features['rsi_7'] = self._rsi(close, 7)
        features['rsi_21'] = self._rsi(close, 21)
        
        # Stochastic
        stoch_k, stoch_d = self._stochastic(high, low, close)
        features['stoch_k'] = stoch_k
        features['stoch_d'] = stoch_d
        features['stoch_cross'] = stoch_k - stoch_d
        
        # === VOLATILITY ===
        atr = self._atr(high, low, close)
        features['atr'] = atr
        features['atr_pct'] = atr / close
        features['atr_z'] = (atr - atr.rolling(20).mean()) / (atr.rolling(20).std() + 1e-10)
        
        # Historical volatility
        returns = close.pct_change()
        features['volatility_10'] = returns.rolling(10).std()
        features['volatility_20'] = returns.rolling(20).std()
        features['volatility_50'] = returns.rolling(50).std()
        
        # === TREND STRENGTH ===
        features['adx'] = self._adx(high, low, close)
        
        # Ichimoku
        ichimoku = self._ichimoku(high, low, close)
        features['ichimoku_tenkan'] = (ichimoku['tenkan'] - close) / close
        features['ichimoku_kijun'] = (ichimoku['kijun'] - close) / close
        features['ichimoku_cloud'] = (ichimoku['senkou_a'] - ichimoku['senkou_b']) / close
        
        # === RETURNS ===
        features['return_1'] = returns
        features['return_3'] = close.pct_change(3)
        features['return_5'] = close.pct_change(5)
        features['return_10'] = close.pct_change(10)
        features['return_20'] = close.pct_change(20)
        
        # === VOLUME ===
        obv = self._obv(close, volume)
        features['obv'] = obv / obv.rolling(20).mean()
        features['obv_slope'] = obv.diff(5)
        
        volume_profile = self._volume_profile(close, volume)
        features['volume_ratio'] = volume_profile['volume_ratio']
        features['volume_trend'] = volume_profile['volume_trend']
        features['volume_volatility'] = volume_profile['volume_volatility']
        
        # VWAP
        vwap = self._vwap(high, low, close, volume)
        features['vwap_dist'] = (close - vwap) / vwap
        
        # === PRICE PATTERNS ===
        # Candle body and shadows
        features['body_size'] = abs(close - open_) / close
        features['upper_shadow'] = (high - np.maximum(open_, close)) / close
        features['lower_shadow'] = (np.minimum(open_, close) - low) / close
        
        # High-Low range
        features['hl_range'] = (high - low) / close
        features['hl_range_ma'] = features['hl_range'].rolling(10).mean()
        
        # === MARKET REGIME ===
        features['regime'] = self._market_regime(close, volume)
        
        # Rolling Hurst (computed every 50 periods)
        if len(close) >= 100:
            hurst_values = []
            for i in range(len(close)):
                if i < 50:
                    hurst_values.append(0.5)
                else:
                    h = self._hurst_exponent(close.iloc[max(0, i-100):i], lags=20)
                    hurst_values.append(h)
            features['hurst'] = hurst_values
        else:
            features['hurst'] = 0.5
        
        # === LAG FEATURES (prevent data leakage) ===
        # Lag all features by 1 period
        features = features.shift(1)
        
        # Drop NaN
        features = features.dropna()
        
        self.feature_names = list(features.columns)
        logger.info(f"Built {len(features.columns)} features from {len(df)} candles")
        
        return features
