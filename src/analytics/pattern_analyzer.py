"""
Pattern Analysis System - Learn from Historical Performance

Analyzes trade database to discover:
- Which pairs perform best
- Best trading hours/days
- Optimal confidence thresholds
- Market regime preferences
- Feature importance patterns
"""
import sqlite3
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class PatternAnalyzer:
    """Analyzes trading patterns to discover what works."""
    
    def __init__(self, db_path: str = 'data/performance.db'):
        self.db_path = db_path
        self.insights = {}
        self.last_analysis_time = None
    
    def analyze_all(self, min_trades: int = 20) -> Dict:
        """Run complete analysis and generate insights."""
        logger.info("🔍 Running pattern analysis...")
        
        insights = {
            'by_symbol': self.analyze_by_symbol(min_trades=min_trades),
            'by_time': self.analyze_by_time(min_trades=min_trades),
            'by_confidence': self.analyze_by_confidence(),
            'by_regime': self.analyze_by_regime(),
            'optimal_hold_times': self.analyze_hold_duration(),
            'timestamp': datetime.now().isoformat()
        }
        
        self.insights = insights
        self.last_analysis_time = datetime.now()
        
        # Save insights to file
        self._save_insights(insights)
        
        return insights
    
    def analyze_by_symbol(self, min_trades: int = 20) -> Dict:
        """Find which pairs perform best."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    symbol,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
                    AVG(ml_confidence) as avg_confidence,
                    SUM(pnl) as total_pnl,
                    AVG(hold_duration_seconds) as avg_hold_seconds
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY symbol
                HAVING COUNT(*) >= ?
                ORDER BY avg_pnl_pct DESC
            ''', (min_trades,))
            
            results = {}
            for row in cursor.fetchall():
                symbol = row['symbol']
                results[symbol] = {
                    'trade_count': row['trade_count'],
                    'avg_pnl_pct': row['avg_pnl_pct'],
                    'win_rate': row['win_rate'],
                    'avg_confidence': row['avg_confidence'],
                    'total_pnl': row['total_pnl'],
                    'avg_hold_hours': row['avg_hold_seconds'] / 3600 if row['avg_hold_seconds'] else 0,
                    'quality_score': self._calculate_quality_score(
                        row['avg_pnl_pct'],
                        row['win_rate'],
                        row['trade_count']
                    )
                }
            
            logger.info(f"📊 Analyzed {len(results)} symbols with {min_trades}+ trades")
            return results
    
    def analyze_by_time(self, min_trades: int = 10) -> Dict:
        """Find best trading hours and days."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # By hour
            cursor_hour = conn.execute('''
                SELECT 
                    hour_of_day,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
                FROM trades
                WHERE hour_of_day IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY hour_of_day
                HAVING COUNT(*) >= ?
                ORDER BY hour_of_day
            ''', (min_trades,))
            
            by_hour = {}
            for row in cursor_hour.fetchall():
                by_hour[row['hour_of_day']] = {
                    'trade_count': row['trade_count'],
                    'avg_pnl_pct': row['avg_pnl_pct'],
                    'win_rate': row['win_rate']
                }
            
            # By day of week
            cursor_day = conn.execute('''
                SELECT 
                    day_of_week,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
                FROM trades
                WHERE day_of_week IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY day_of_week
                HAVING COUNT(*) >= ?
                ORDER BY day_of_week
            ''', (min_trades,))
            
            by_day = {}
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            for row in cursor_day.fetchall():
                by_day[day_names[row['day_of_week']]] = {
                    'trade_count': row['trade_count'],
                    'avg_pnl_pct': row['avg_pnl_pct'],
                    'win_rate': row['win_rate']
                }
            
            return {'by_hour': by_hour, 'by_day': by_day}
    
    def analyze_by_confidence(self) -> Dict:
        """Find optimal ML confidence thresholds."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    CASE 
                        WHEN ml_confidence < 0.60 THEN '50-60%'
                        WHEN ml_confidence < 0.70 THEN '60-70%'
                        WHEN ml_confidence < 0.80 THEN '70-80%'
                        WHEN ml_confidence < 0.90 THEN '80-90%'
                        ELSE '90-100%'
                    END as conf_bucket,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
                FROM trades
                WHERE ml_confidence IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY conf_bucket
                ORDER BY conf_bucket
            ''')
            
            results = {}
            for row in cursor.fetchall():
                results[row['conf_bucket']] = {
                    'trade_count': row['trade_count'],
                    'avg_pnl_pct': row['avg_pnl_pct'],
                    'win_rate': row['win_rate']
                }
            
            return results
    
    def analyze_by_regime(self) -> Dict:
        """Find which market regimes produce best results."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    market_regime,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
                    AVG(volatility) as avg_volatility
                FROM trades
                WHERE market_regime IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY market_regime
                ORDER BY avg_pnl_pct DESC
            ''')
            
            results = {}
            for row in cursor.fetchall():
                regime = row['market_regime']
                if regime:
                    results[regime] = {
                        'trade_count': row['trade_count'],
                        'avg_pnl_pct': row['avg_pnl_pct'],
                        'win_rate': row['win_rate'],
                        'avg_volatility': row['avg_volatility']
                    }
            
            return results
    
    def analyze_hold_duration(self) -> Dict:
        """Find optimal holding periods."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    CASE 
                        WHEN hold_duration_seconds < 300 THEN '< 5min'
                        WHEN hold_duration_seconds < 900 THEN '5-15min'
                        WHEN hold_duration_seconds < 1800 THEN '15-30min'
                        WHEN hold_duration_seconds < 3600 THEN '30-60min'
                        ELSE '> 1hr'
                    END as duration_bucket,
                    COUNT(*) as trade_count,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
                FROM trades
                WHERE hold_duration_seconds IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY duration_bucket
                ORDER BY 
                    CASE duration_bucket
                        WHEN '< 5min' THEN 1
                        WHEN '5-15min' THEN 2
                        WHEN '15-30min' THEN 3
                        WHEN '30-60min' THEN 4
                        ELSE 5
                    END
            ''')
            
            results = {}
            for row in cursor.fetchall():
                results[row['duration_bucket']] = {
                    'trade_count': row['trade_count'],
                    'avg_pnl_pct': row['avg_pnl_pct'],
                    'win_rate': row['win_rate']
                }
            
            return results
    
    def get_symbol_recommendation(self, symbol: str) -> Dict:
        """Get actionable recommendations for a specific symbol."""
        if not self.insights or 'by_symbol' not in self.insights:
            self.analyze_all()
        
        symbol_data = self.insights['by_symbol'].get(symbol, {})
        
        if not symbol_data:
            return {
                'recommendation': 'UNKNOWN',
                'reason': 'Insufficient data',
                'confidence_adjust': 0,
                'position_size_multiplier': 1.0
            }
        
        quality = symbol_data.get('quality_score', 0)
        win_rate = symbol_data.get('win_rate', 0)
        
        if quality > 0.7 and win_rate > 0.6:
            return {
                'recommendation': 'PREFERRED',
                'reason': f"High quality ({quality:.2f}) + good win rate ({win_rate:.1%})",
                'confidence_adjust': -0.02,  # Lower threshold (more trades)
                'position_size_multiplier': 1.2  # 20% larger positions
            }
        elif quality < 0.3 or win_rate < 0.45:
            return {
                'recommendation': 'AVOID',
                'reason': f"Low quality ({quality:.2f}) or poor win rate ({win_rate:.1%})",
                'confidence_adjust': +0.05,  # Higher threshold (fewer trades)
                'position_size_multiplier': 0.7  # 30% smaller positions
            }
        else:
            return {
                'recommendation': 'NEUTRAL',
                'reason': 'Average performance',
                'confidence_adjust': 0,
                'position_size_multiplier': 1.0
            }
    
    def _calculate_quality_score(self, avg_pnl: float, win_rate: float, trade_count: int) -> float:
        """Calculate overall quality score (0-1) for a symbol."""
        # Normalize components
        pnl_score = min(1.0, max(0, (avg_pnl + 1) / 2))  # -1% to +1% maps to 0-1
        win_rate_score = win_rate  # Already 0-1
        volume_score = min(1.0, trade_count / 50)  # More trades = more confidence
        
        # Weighted combination
        return (pnl_score * 0.4 + win_rate_score * 0.4 + volume_score * 0.2)
    
    def _save_insights(self, insights: Dict):
        """Save insights to disk for dashboard access."""
        try:
            output_path = Path('data/pattern_insights.json')
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w') as f:
                json.dump(insights, f, indent=2, default=str)
            
            logger.info(f"💾 Insights saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save insights: {e}")
    
    def get_best_trading_hours(self, top_n: int = 3) -> List[int]:
        """Get the best hours to trade based on historical performance."""
        if not self.insights or 'by_time' not in self.insights:
            self.analyze_all()
        
        by_hour = self.insights['by_time'].get('by_hour', {})
        
        # Score each hour by win rate and avg P&L
        hour_scores = {}
        for hour, data in by_hour.items():
            if data['trade_count'] >= 5:  # Min sample size
                score = data['win_rate'] * 0.6 + (data['avg_pnl_pct'] / 2) * 0.4
                hour_scores[hour] = score
        
        # Return top N hours
        sorted_hours = sorted(hour_scores.items(), key=lambda x: x[1], reverse=True)
        return [hour for hour, score in sorted_hours[:top_n]]
