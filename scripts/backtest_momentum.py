#!/usr/bin/env python3
"""
Backtest Momentum Scanner on Historical Data

This script replays historical kline data through the momentum scanner
to measure detection latency, filter pass rates, and false positive rates.

Usage:
    python scripts/backtest_momentum.py \
        --symbol DASHUSDT \
        --start "2025-01-15 10:00:00" \
        --end "2025-01-15 16:00:00" \
        --output results/dash_backtest.csv
"""

import sys
import os
import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import csv

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from binance.client import Client
from config.config import Config
from src.utils.momentum_scanner import MomentumScanner


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestMomentumScanner:
    """Backtest momentum scanner on historical data"""
    
    def __init__(self, config: Config, symbol: str, start: datetime, end: datetime):
        self.config = config
        self.symbol = symbol
        self.start = start
        self.end = end
        self.client = Client(config.api_key, config.api_secret, testnet=False)
        self.scanner = MomentumScanner(self.client, config)
        self.results = []
        
    async def fetch_historical_klines(self, interval: str) -> List[List]:
        """Fetch historical klines for symbol and interval"""
        logger.info(f"Fetching {interval} klines for {self.symbol} from {self.start} to {self.end}")
        
        start_ms = int(self.start.timestamp() * 1000)
        end_ms = int(self.end.timestamp() * 1000)
        
        try:
            klines = self.client.get_historical_klines(
                symbol=self.symbol,
                interval=interval,
                start_str=start_ms,
                end_str=end_ms
            )
            logger.info(f"Fetched {len(klines)} {interval} klines for {self.symbol}")
            return klines
        except Exception as e:
            logger.error(f"Error fetching {interval} klines for {self.symbol}: {e}")
            return []
    
    async def simulate_scan_at_time(self, timestamp: datetime, 
                                   klines_5m: List[List],
                                   klines_15m: List[List],
                                   klines_1h: List[List]) -> Dict[str, Any]:
        """Simulate scanner execution at a specific timestamp"""
        
        # Get klines up to this timestamp
        ts_ms = int(timestamp.timestamp() * 1000)
        
        klines_5m_slice = [k for k in klines_5m if k[0] <= ts_ms]
        klines_15m_slice = [k for k in klines_15m if k[0] <= ts_ms]
        klines_1h_slice = [k for k in klines_1h if k[0] <= ts_ms]
        
        if not klines_5m_slice or not klines_15m_slice or not klines_1h_slice:
            return None
        
        # Compute indicators
        try:
            indicators = self.scanner._compute_indicators(
                self.symbol,
                klines_5m_slice,
                klines_15m_slice,
                klines_1h_slice
            )
        except Exception as e:
            logger.warning(f"Error computing indicators at {timestamp}: {e}")
            return None
        
        # Apply filters
        try:
            filter_results = self.scanner._apply_filters(self.symbol, indicators)
        except Exception as e:
            logger.warning(f"Error applying filters at {timestamp}: {e}")
            return None
        
        # Get current price (close of latest 5m candle)
        current_price = float(klines_5m_slice[-1][4])
        
        return {
            'timestamp': timestamp,
            'price': current_price,
            'filters_passed': filter_results['filters_passed'],
            'filters_failed': len(filter_results['filters_failed']),
            'momentum_score': indicators.get('momentum_score', 0),
            'volume_surge': indicators.get('vol_ratio_5m', 0),
            'rsi_5m': indicators.get('rsi_5m', 0),
            'adx_15m': indicators.get('adx_15m', 0),
            'filter_details': filter_results
        }
    
    async def run_backtest(self):
        """Run backtest over the time range"""
        logger.info(f"Starting backtest for {self.symbol} from {self.start} to {self.end}")
        
        # Fetch historical data
        klines_5m = await self.fetch_historical_klines('5m')
        klines_15m = await self.fetch_historical_klines('15m')
        klines_1h = await self.fetch_historical_klines('1h')
        
        if not klines_5m or not klines_15m or not klines_1h:
            logger.error("Failed to fetch historical klines")
            return
        
        # Simulate scanner at each 5m interval
        current_time = self.start
        breakout_detected = False
        detection_time = None
        entry_price = None
        peak_price = float(klines_5m[0][4])
        
        while current_time <= self.end:
            result = await self.simulate_scan_at_time(current_time, klines_5m, klines_15m, klines_1h)
            
            if result:
                self.results.append(result)
                
                # Track peak price
                if result['price'] > peak_price:
                    peak_price = result['price']
                
                # Detection logic: 7+ filters passed
                if result['filters_passed'] >= 7 and not breakout_detected:
                    breakout_detected = True
                    detection_time = current_time
                    entry_price = result['price']
                    
                    logger.info(f"🚀 BREAKOUT DETECTED at {current_time}")
                    logger.info(f"   Price: ${entry_price:.2f}")
                    logger.info(f"   Filters Passed: {result['filters_passed']}/10")
                    logger.info(f"   Momentum Score: {result['momentum_score']:.1f}/10")
                    logger.info(f"   Volume Surge: {result['volume_surge']:.1f}x")
                
            current_time += timedelta(minutes=5)
        
        # Calculate metrics
        self._calculate_metrics(detection_time, entry_price, peak_price)
    
    def _calculate_metrics(self, detection_time: datetime, entry_price: float, peak_price: float):
        """Calculate backtest metrics"""
        
        if not self.results:
            logger.error("No results to analyze")
            return
        
        logger.info("\n" + "=" * 60)
        logger.info("BACKTEST RESULTS")
        logger.info("=" * 60)
        
        # Detection metrics
        if detection_time:
            latency = (detection_time - self.start).total_seconds() / 60
            logger.info(f"Detection Latency: {latency:.1f} minutes")
            
            if entry_price:
                pct_from_start = ((entry_price / float(self.results[0]['price'])) - 1) * 100
                logger.info(f"Entry Price: ${entry_price:.2f} ({pct_from_start:+.1f}% from start)")
                
                pct_to_peak = ((peak_price / entry_price) - 1) * 100
                logger.info(f"Peak Price: ${peak_price:.2f} ({pct_to_peak:+.1f}% from entry)")
                
                # Simulated trade outcomes
                sl_pct = self.config.momentum_stop_loss_pct
                tp_pct = self.config.momentum_take_profit_pct
                
                sl_price = entry_price * (1 - sl_pct / 100)
                tp_price = entry_price * (1 + tp_pct / 100)
                
                if peak_price >= tp_price:
                    logger.info(f"✅ Take Profit Hit: ${tp_price:.2f} (+{tp_pct}%)")
                    outcome = "TP"
                elif any(r['price'] <= sl_price for r in self.results if r['timestamp'] >= detection_time):
                    logger.info(f"❌ Stop Loss Hit: ${sl_price:.2f} (-{sl_pct}%)")
                    outcome = "SL"
                else:
                    logger.info(f"⏸️  Neither TP nor SL hit in timeframe")
                    outcome = "OPEN"
        else:
            logger.info("⚠️  No breakout detected (filters passed < 7)")
            outcome = "MISS"
        
        # Filter pass rate over time
        filters_passed = [r['filters_passed'] for r in self.results]
        avg_filters = sum(filters_passed) / len(filters_passed)
        max_filters = max(filters_passed)
        
        logger.info(f"\nFilter Statistics:")
        logger.info(f"  Average Filters Passed: {avg_filters:.1f}/10")
        logger.info(f"  Max Filters Passed: {max_filters}/10")
        logger.info(f"  Scans with ≥7 filters: {sum(1 for f in filters_passed if f >= 7)}")
        logger.info(f"  Scans with 10/10 filters: {sum(1 for f in filters_passed if f == 10)}")
        
        # Price action
        start_price = self.results[0]['price']
        end_price = self.results[-1]['price']
        pct_change = ((end_price / start_price) - 1) * 100
        
        logger.info(f"\nPrice Action:")
        logger.info(f"  Start: ${start_price:.2f}")
        logger.info(f"  End: ${end_price:.2f}")
        logger.info(f"  Change: {pct_change:+.1f}%")
        logger.info(f"  Peak: ${peak_price:.2f} ({((peak_price / start_price) - 1) * 100:+.1f}%)")
        
        logger.info("=" * 60 + "\n")
        
        return outcome if detection_time else "MISS"
    
    def save_results(self, output_path: str):
        """Save results to CSV"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'price', 'filters_passed', 'filters_failed',
                'momentum_score', 'volume_surge', 'rsi_5m', 'adx_15m'
            ])
            
            for r in self.results:
                writer.writerow([
                    r['timestamp'].isoformat(),
                    f"{r['price']:.2f}",
                    r['filters_passed'],
                    r['filters_failed'],
                    f"{r['momentum_score']:.2f}",
                    f"{r['volume_surge']:.2f}",
                    f"{r['rsi_5m']:.2f}",
                    f"{r['adx_15m']:.2f}"
                ])
        
        logger.info(f"Results saved to {output_path}")


async def main():
    parser = argparse.ArgumentParser(description='Backtest Momentum Scanner')
    parser.add_argument('--symbol', type=str, required=True, help='Trading pair (e.g., DASHUSDT)')
    parser.add_argument('--start', type=str, required=True, help='Start time (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--end', type=str, required=True, help='End time (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--output', type=str, default='results/backtest.csv', help='Output CSV path')
    
    args = parser.parse_args()
    
    # Parse timestamps
    start = datetime.strptime(args.start, '%Y-%m-%d %H:%M:%S')
    end = datetime.strptime(args.end, '%Y-%m-%d %H:%M:%S')
    
    # Load config
    config = Config()
    
    # Run backtest
    backtest = BacktestMomentumScanner(config, args.symbol, start, end)
    await backtest.run_backtest()
    backtest.save_results(args.output)


if __name__ == '__main__':
    asyncio.run(main())
