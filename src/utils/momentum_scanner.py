"""
Momentum Scanner with Anti-Pump-and-Dump Filters

Scans all USDT pairs for explosive breakout moves while filtering out:
- Pump-and-dump schemes
- Parabolic late entries
- Thin liquidity traps
- Market-wide beta moves
- Overbought conditions

Uses multi-timeframe confirmation (5m/15m/1h) and 10 strict filters.
"""
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Technical indicators
from ta.trend import ADXIndicator, EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import VolumeWeightedAveragePrice

from utils.order_book_analyzer import OrderBookAnalyzer


logger = logging.getLogger(__name__)


class MomentumScanner:
    """
    Real-time momentum/breakout scanner with anti-pump-and-dump protection
    """
    
    def __init__(self, client: Client, config, order_book_analyzer: OrderBookAnalyzer = None):
        self.client = client
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Order book analyzer for liquidity checks
        self.order_book_analyzer = order_book_analyzer or OrderBookAnalyzer(client)
        
        # Scanner settings
        self.min_volume_usdt = config.momentum_min_volume_usdt
        self.alert_threshold = config.momentum_alert_threshold  # 7/10 for alerts
        self.trade_threshold = config.momentum_trade_threshold  # 10/10 for auto-trade
        
        # Leverage tokens to exclude (pump-prone)
        self.excluded_tokens = {
            'UP', 'DOWN', 'BULL', 'BEAR', '3L', '3S', '5L', '5S',
            'BUSD', 'USDC', 'TUSD', 'USDP', 'FDUSD'  # Stablecoins
        }
        
        # Caching for multi-timeframe data
        self.kline_cache_15m = {}  # Refresh every 3 cycles
        self.kline_cache_1h = {}   # Refresh every 12 cycles
        self.cache_15m_age = 0
        self.cache_1h_age = 0
        self.cycle_count = 0
        
        # BTC/ETH reference data for correlation check
        self.btc_data = None
        self.eth_data = None
        
        # Rate limiting
        self.semaphore = asyncio.Semaphore(10)  # Max 10 concurrent requests
        
        self.logger.info(
            f"MomentumScanner initialized: min_vol ${self.min_volume_usdt:,.0f}, "
            f"thresholds {self.alert_threshold}/{self.trade_threshold}"
        )
    
    async def scan(self) -> List[Dict]:
        """
        Perform full momentum scan across all USDT pairs
        
        Returns:
            List of momentum signals that passed filters
        """
        self.cycle_count += 1
        self.logger.info(f"🔍 Starting momentum scan cycle #{self.cycle_count}")
        
        try:
            # Step 1: Get universe of tradeable pairs
            symbols = await self._get_universe()
            if not symbols:
                return []
            
            # Step 2: Fetch market reference data (BTC/ETH)
            await self._fetch_reference_data()
            
            # Step 3: Fetch klines for all symbols (with caching)
            klines_5m = await self._batch_fetch_klines(symbols, '5m')
            klines_15m = await self._get_cached_klines(symbols, '15m')
            klines_1h = await self._get_cached_klines(symbols, '1h')
            
            # Step 4: Analyze each symbol
            candidates = []
            for symbol in symbols:
                if symbol not in klines_5m or symbol not in klines_15m or symbol not in klines_1h:
                    continue
                
                try:
                    # Compute indicators
                    indicators = self._compute_indicators(
                        symbol,
                        klines_5m[symbol],
                        klines_15m[symbol],
                        klines_1h[symbol]
                    )
                    
                    # Apply filters
                    filter_result = self._apply_filters(symbol, indicators)
                    
                    # Check if passes alert threshold
                    if filter_result['filters_passed'] >= self.alert_threshold:
                        # Finalize signal with liquidity check (expensive)
                        signal = await self._finalize_signal(symbol, indicators, filter_result)
                        if signal:
                            candidates.append(signal)
                            self.logger.info(
                                f"✅ {symbol}: {filter_result['filters_passed']}/10 filters, "
                                f"score {signal['momentum_score']:.1f}/10"
                            )
                
                except Exception as e:
                    self.logger.warning(f"Error analyzing {symbol}: {e}")
                    continue
            
            # Sort by score descending
            candidates.sort(key=lambda x: x['momentum_score'], reverse=True)
            
            self.logger.info(
                f"✅ Scan complete: {len(candidates)} momentum signals found "
                f"(scanned {len(symbols)} pairs)"
            )
            
            return candidates
        
        except Exception as e:
            self.logger.error(f"Momentum scan failed: {e}", exc_info=True)
            return []
    
    async def _get_universe(self) -> List[str]:
        """Get list of tradeable USDT pairs filtered by volume"""
        try:
            # Get 24h tickers
            tickers = self.client.get_ticker()
            
            # Filter: USDT pairs, sufficient volume, not leverage tokens
            candidates = []
            for ticker in tickers:
                symbol = ticker['symbol']
                
                # Must end with USDT
                if not symbol.endswith('USDT'):
                    continue
                
                # Exclude leverage tokens
                if any(token in symbol for token in self.excluded_tokens):
                    continue
                
                # Volume filter
                quote_volume = float(ticker['quoteVolume'])
                if quote_volume < self.min_volume_usdt:
                    continue
                
                candidates.append(symbol)
            
            # Sort by volume, take top 150 to avoid rate limits
            candidates_with_vol = [
                (sym, float([t for t in tickers if t['symbol'] == sym][0]['quoteVolume']))
                for sym in candidates
            ]
            candidates_with_vol.sort(key=lambda x: x[1], reverse=True)
            final = [sym for sym, _ in candidates_with_vol[:150]]
            
            self.logger.info(f"Universe: {len(final)} pairs (min volume ${self.min_volume_usdt:,.0f})")
            return final
        
        except Exception as e:
            self.logger.error(f"Failed to get universe: {e}")
            return []
    
    async def _fetch_reference_data(self):
        """Fetch BTC and ETH data for correlation checks"""
        try:
            btc_klines = self.client.get_klines(symbol='BTCUSDT', interval='15m', limit=50)
            eth_klines = self.client.get_klines(symbol='ETHUSDT', interval='15m', limit=50)
            
            self.btc_data = self._klines_to_df(btc_klines)
            self.eth_data = self._klines_to_df(eth_klines)
        
        except Exception as e:
            self.logger.warning(f"Failed to fetch BTC/ETH reference: {e}")
    
    async def _batch_fetch_klines(self, symbols: List[str], interval: str, limit: int = 150) -> Dict:
        """Fetch klines for multiple symbols with rate limiting"""
        results = {}
        
        async def fetch_one(symbol):
            async with self.semaphore:
                try:
                    klines = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
                    )
                    return symbol, klines
                except BinanceAPIException as e:
                    self.logger.debug(f"API error fetching {symbol} {interval}: {e}")
                    return symbol, None
                except Exception as e:
                    self.logger.debug(f"Error fetching {symbol} {interval}: {e}")
                    return symbol, None
        
        # Fetch concurrently
        tasks = [fetch_one(sym) for sym in symbols]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for response in responses:
            if isinstance(response, Exception):
                continue
            symbol, klines = response
            if klines:
                results[symbol] = klines
        
        self.logger.debug(f"Fetched {len(results)}/{len(symbols)} pairs for {interval}")
        return results
    
    async def _get_cached_klines(self, symbols: List[str], interval: str) -> Dict:
        """Get klines with caching for 15m and 1h timeframes"""
        if interval == '15m':
            self.cache_15m_age += 1
            if self.cache_15m_age >= 3 or not self.kline_cache_15m:
                self.logger.debug("Refreshing 15m cache")
                self.kline_cache_15m = await self._batch_fetch_klines(symbols, '15m', limit=100)
                self.cache_15m_age = 0
            return self.kline_cache_15m
        
        elif interval == '1h':
            self.cache_1h_age += 1
            if self.cache_1h_age >= 12 or not self.kline_cache_1h:
                self.logger.debug("Refreshing 1h cache")
                self.kline_cache_1h = await self._batch_fetch_klines(symbols, '1h', limit=50)
                self.cache_1h_age = 0
            return self.kline_cache_1h
        
        else:
            return await self._batch_fetch_klines(symbols, interval)
    
    def _klines_to_df(self, klines: list) -> pd.DataFrame:
        """Convert klines to DataFrame"""
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
            df[col] = pd.to_numeric(df[col])
        
        return df
    
    def _compute_indicators(self, symbol: str, klines_5m: list, klines_15m: list, klines_1h: list) -> Dict:
        """Compute all technical indicators across timeframes"""
        # Convert to dataframes
        df_5m = self._klines_to_df(klines_5m)
        df_15m = self._klines_to_df(klines_15m)
        df_1h = self._klines_to_df(klines_1h)
        
        indicators = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
        }
        
        # 5m indicators
        indicators.update(self._compute_timeframe_indicators(df_5m, '5m'))
        
        # 15m indicators
        indicators.update(self._compute_timeframe_indicators(df_15m, '15m'))
        
        # 1h indicators
        indicators.update(self._compute_timeframe_indicators(df_1h, '1h'))
        
        # Price changes
        indicators['price_change_5m'] = (df_5m['close'].iloc[-1] / df_5m['close'].iloc[-2] - 1) * 100
        indicators['price_change_15m'] = (df_15m['close'].iloc[-1] / df_15m['close'].iloc[-4] - 1) * 100  # Last hour
        indicators['price_change_1h'] = (df_1h['close'].iloc[-1] / df_1h['close'].iloc[-2] - 1) * 100
        indicators['price_change_4h'] = (df_1h['close'].iloc[-1] / df_1h['close'].iloc[-5] - 1) * 100 if len(df_1h) >= 5 else 0
        
        return indicators
    
    def _compute_timeframe_indicators(self, df: pd.DataFrame, timeframe: str) -> Dict:
        """Compute indicators for a single timeframe"""
        try:
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume']
            
            # RSI
            rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
            
            # ADX
            adx_ind = ADXIndicator(high, low, close, window=14)
            adx = adx_ind.adx().iloc[-1]
            
            # ATR
            atr_ind = AverageTrueRange(high, low, close, window=14)
            atr = atr_ind.average_true_range().iloc[-1]
            atr_pct = (atr / close.iloc[-1]) * 100
            
            # Bollinger Bands
            bb = BollingerBands(close, window=20, window_dev=2)
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_mid = bb.bollinger_mavg().iloc[-1]
            bb_width = (bb_upper - bb_lower) / bb_mid * 100
            
            # Historical BB width for expansion calculation
            bb_width_series = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg() * 100
            bb_expansion = bb_width / bb_width_series.median() if bb_width_series.median() > 0 else 1.0
            
            # EMAs
            ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
            ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1] if len(df) >= 50 else ema20
            
            # Volume ratio
            vol_sma = volume.rolling(20).mean().iloc[-1]
            vol_ratio = volume.iloc[-1] / vol_sma if vol_sma > 0 else 1.0
            
            # Sustained volume check (last 3 candles)
            last_3_vols = volume.iloc[-3:].values
            vol_sma_last_3 = [volume.iloc[:i].rolling(20).mean().iloc[-1] for i in range(-3, 0)]
            sustained_vol = all(v >= 1.5 * sma for v, sma in zip(last_3_vols, vol_sma_last_3))
            vol_increasing = sum(1 for i in range(1, 3) if last_3_vols[i] > last_3_vols[i-1]) >= 2
            
            # Consolidation check (median ATR% over last 24 candles for 5m = 2h)
            lookback = 24 if timeframe == '5m' else 12  # Adjust for timeframe
            if len(df) >= lookback:
                atr_series = atr_ind.average_true_range().iloc[-lookback:]
                close_series = close.iloc[-lookback:]
                atr_pct_series = (atr_series / close_series) * 100
                median_atr_pct = atr_pct_series.median()
                consolidation = median_atr_pct < 3.0 and bb_expansion < 1.2
            else:
                consolidation = False
            
            return {
                f'rsi_{timeframe}': rsi,
                f'adx_{timeframe}': adx,
                f'atr_{timeframe}': atr,
                f'atr_pct_{timeframe}': atr_pct,
                f'bb_width_{timeframe}': bb_width,
                f'bb_expansion_{timeframe}': bb_expansion,
                f'ema20_{timeframe}': ema20,
                f'ema50_{timeframe}': ema50,
                f'vol_ratio_{timeframe}': vol_ratio,
                f'sustained_vol_{timeframe}': sustained_vol,
                f'vol_increasing_{timeframe}': vol_increasing,
                f'consolidation_{timeframe}': consolidation,
                f'current_price': close.iloc[-1],
            }
        
        except Exception as e:
            self.logger.warning(f"Indicator calculation error ({timeframe}): {e}")
            return {}
    
    def _apply_filters(self, symbol: str, indicators: Dict) -> Dict:
        """
        Apply 10 anti-pump-and-dump filters
        
        Returns:
            Dict with filters_passed, filters_failed, reasons
        """
        filters = []
        
        # Filter 1: Sustained volume
        passed_1 = (
            indicators.get('sustained_vol_5m', False) and
            indicators.get('vol_increasing_5m', False) and
            indicators.get('vol_ratio_5m', 0) >= 3.0
        )
        filters.append({
            'name': 'Sustained Volume',
            'passed': passed_1,
            'reason': f"Vol ratio {indicators.get('vol_ratio_5m', 0):.1f}x, sustained={indicators.get('sustained_vol_5m', False)}"
        })
        
        # Filter 2: Parabolic rejection
        change_15m = indicators.get('price_change_15m', 0)
        change_1h = indicators.get('price_change_1h', 0)
        had_consolidation = indicators.get('consolidation_5m', False)
        passed_2 = not ((change_15m > 20 or change_1h > 40) and not had_consolidation)
        filters.append({
            'name': 'Parabolic Rejection',
            'passed': passed_2,
            'reason': f"15m {change_15m:.1f}%, 1h {change_1h:.1f}%, consol={had_consolidation}"
        })
        
        # Filter 3: Order book depth (will be checked later in finalize)
        filters.append({
            'name': 'Order Book Depth',
            'passed': True,  # Placeholder - checked in finalize_signal
            'reason': 'Deferred to final check'
        })
        
        # Filter 4: Consolidation requirement
        passed_4 = indicators.get('consolidation_5m', False)
        filters.append({
            'name': 'Prior Consolidation',
            'passed': passed_4,
            'reason': f"ATR%={indicators.get('atr_pct_5m', 0):.2f}, expansion={indicators.get('bb_expansion_5m', 0):.2f}"
        })
        
        # Filter 5: Time-based filter (late entry)
        change_4h = indicators.get('price_change_4h', 0)
        passed_5 = not (change_4h > 15)  # Simplified - full check would need micro-consolidation detection
        filters.append({
            'name': 'Time-based Filter',
            'passed': passed_5,
            'reason': f"4h change {change_4h:.1f}%"
        })
        
        # Filter 6: Volume floor (already enforced in universe selection)
        filters.append({
            'name': 'Volume Floor',
            'passed': True,
            'reason': f"Min ${self.min_volume_usdt:,.0f}"
        })
        
        # Filter 7: Independent move vs market
        if self.btc_data is not None and self.eth_data is not None:
            btc_change_15m = (self.btc_data['close'].iloc[-1] / self.btc_data['close'].iloc[-4] - 1) * 100
            eth_change_15m = (self.eth_data['close'].iloc[-1] / self.eth_data['close'].iloc[-4] - 1) * 100
            market_max = max(btc_change_15m, eth_change_15m)
            
            # Only apply if market is positive
            if market_max > 0:
                passed_7 = change_15m >= 2 * market_max
            else:
                passed_7 = True  # Market down, don't penalize
        else:
            passed_7 = True  # No reference data
        
        filters.append({
            'name': 'Independent Move',
            'passed': passed_7,
            'reason': f"Asset 15m {change_15m:.1f}% vs market"
        })
        
        # Filter 8: Multi-timeframe alignment
        mtf_aligned = (
            indicators.get('price_change_5m', 0) > 0 and
            indicators.get('price_change_15m', 0) > 0 and
            indicators.get('price_change_1h', 0) > 0 and
            indicators.get('adx_15m', 0) > 25 and
            indicators.get('adx_1h', 0) > 25
        )
        filters.append({
            'name': 'MTF Alignment',
            'passed': mtf_aligned,
            'reason': f"ADX 15m={indicators.get('adx_15m', 0):.0f}, 1h={indicators.get('adx_1h', 0):.0f}"
        })
        
        # Filter 9: RSI bounds (momentum zone)
        rsi_5m = indicators.get('rsi_5m', 50)
        rsi_15m = indicators.get('rsi_15m', 50)
        passed_9 = (50 <= rsi_5m <= 80) and (50 <= rsi_15m <= 80)
        filters.append({
            'name': 'RSI Bounds',
            'passed': passed_9,
            'reason': f"RSI 5m={rsi_5m:.0f}, 15m={rsi_15m:.0f}"
        })
        
        # Filter 10: Volatility cap
        atr_pct_5m = indicators.get('atr_pct_5m', 0)
        passed_10 = atr_pct_5m <= 5.0
        filters.append({
            'name': 'Volatility Cap',
            'passed': passed_10,
            'reason': f"ATR% {atr_pct_5m:.2f}%"
        })
        
        # Summary
        filters_passed = sum(1 for f in filters if f['passed'])
        filters_failed = [f for f in filters if not f['passed']]
        
        return {
            'filters_passed': filters_passed,
            'filters_failed': filters_failed,
            'all_filters': filters
        }
    
    async def _finalize_signal(self, symbol: str, indicators: Dict, filter_result: Dict) -> Optional[Dict]:
        """
        Finalize signal with liquidity check and scoring
        
        Returns:
            Complete signal dict or None if liquidity check fails
        """
        try:
            # Order book depth check (expensive - only for finalists)
            is_liquid, depth_info = self.order_book_analyzer.is_liquid(
                symbol,
                min_each_side=50000,  # $50k each side
                pct=0.01
            )
            
            if not is_liquid:
                self.logger.debug(f"{symbol}: Failed liquidity check")
                # Update filter result
                for f in filter_result['all_filters']:
                    if f['name'] == 'Order Book Depth':
                        f['passed'] = False
                        f['reason'] = f"Bid ${depth_info['bid_usdt']:,.0f}, Ask ${depth_info['ask_usdt']:,.0f}"
                filter_result['filters_passed'] -= 1
                
                # If this drops below alert threshold, reject
                if filter_result['filters_passed'] < self.alert_threshold:
                    return None
            
            # Calculate momentum score (0-10)
            momentum_score = self._calculate_momentum_score(indicators)
            
            # Calculate entry/stop/target
            current_price = indicators['current_price']
            atr_5m = indicators.get('atr_5m', current_price * 0.02)
            
            recommended_entry = current_price - (0.5 * atr_5m)  # Pullback entry
            stop_loss_pct = self.config.momentum_stop_loss_pct / 100
            take_profit_pct = self.config.momentum_take_profit_pct / 100
            
            stop_loss = recommended_entry * (1 - stop_loss_pct)
            take_profit = recommended_entry * (1 + take_profit_pct)
            
            # Risk level
            liquidity_score = min(depth_info['bid_usdt'], depth_info['ask_usdt']) / 100000  # Normalize to 0-1
            liquidity_score = min(liquidity_score, 1.0)
            
            from utils.momentum_risk_manager import MomentumRiskManager
            risk_mgr = MomentumRiskManager(self.config)
            risk_level = risk_mgr.calculate_risk_level(
                indicators.get('atr_pct_5m', 3.0),
                liquidity_score,
                momentum_score
            )
            
            # Build signal
            signal = {
                'symbol': symbol,
                'timestamp': indicators['timestamp'],
                'momentum_score': momentum_score,
                'filters_passed': filter_result['filters_passed'],
                'filters_failed': [f['name'] for f in filter_result['filters_failed']],
                'current_price': current_price,
                'recommended_entry': recommended_entry,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'risk_level': risk_level,
                'indicators': {
                    'rsi_5m': indicators.get('rsi_5m', 0),
                    'rsi_15m': indicators.get('rsi_15m', 0),
                    'adx_15m': indicators.get('adx_15m', 0),
                    'adx_1h': indicators.get('adx_1h', 0),
                    'atr_pct_5m': indicators.get('atr_pct_5m', 0),
                    'vol_ratio_5m': indicators.get('vol_ratio_5m', 0),
                    'price_change_5m': indicators.get('price_change_5m', 0),
                    'price_change_15m': indicators.get('price_change_15m', 0),
                    'price_change_1h': indicators.get('price_change_1h', 0),
                },
                'liquidity': {
                    'bid_usdt': depth_info['bid_usdt'],
                    'ask_usdt': depth_info['ask_usdt'],
                    'is_liquid': is_liquid
                },
                'filter_details': filter_result['all_filters']
            }
            
            return signal
        
        except Exception as e:
            self.logger.error(f"Error finalizing signal for {symbol}: {e}")
            return None
    
    def _calculate_momentum_score(self, indicators: Dict) -> float:
        """
        Calculate momentum score (0-10) based on weighted indicators
        
        Weights:
        - Price momentum (5m/15m/1h): 35%
        - Volume surge: 25%
        - ADX strength: 20%
        - BB expansion: 10%
        - MTF alignment: 10%
        """
        score = 0.0
        
        # Price momentum (0-3.5 points)
        price_momentum = (
            indicators.get('price_change_5m', 0) * 0.1 +
            indicators.get('price_change_15m', 0) * 0.15 +
            indicators.get('price_change_1h', 0) * 0.10
        )
        price_score = np.clip(price_momentum / 10, 0, 3.5)  # Scale: 10% total = 3.5 points
        score += price_score
        
        # Volume surge (0-2.5 points)
        vol_ratio = indicators.get('vol_ratio_5m', 1.0)
        vol_score = np.clip((vol_ratio - 1) / 4, 0, 2.5) * 2.5  # 5x volume = 2.5 points
        score += vol_score
        
        # ADX strength (0-2.0 points)
        adx_avg = (indicators.get('adx_15m', 25) + indicators.get('adx_1h', 25)) / 2
        adx_score = np.clip((adx_avg - 25) / 15, 0, 2.0) * 2.0  # ADX 40+ = 2.0 points
        score += adx_score
        
        # BB expansion (0-1.0 points)
        bb_expansion = indicators.get('bb_expansion_5m', 1.0)
        bb_score = np.clip((bb_expansion - 1) / 2, 0, 1.0) * 1.0  # 3x expansion = 1.0 point
        score += bb_score
        
        # MTF alignment (0-1.0 points)
        mtf_score = 0.0
        if (indicators.get('price_change_5m', 0) > 0 and
            indicators.get('price_change_15m', 0) > 0 and
            indicators.get('price_change_1h', 0) > 0):
            mtf_score = 1.0
        score += mtf_score
        
        return round(score, 1)
