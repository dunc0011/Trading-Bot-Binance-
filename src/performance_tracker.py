"""
Performance Tracker - Store and analyze trading performance
"""
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Track trading performance and store in database"""
    
    def __init__(self, db_path: str = 'data/performance.db'):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    size REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    ml_confidence REAL,
                    entry_time TEXT,
                    exit_time TEXT,
                    reason TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_value REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    open_positions INTEGER,
                    total_trades INTEGER,
                    win_rate REAL
                )
            ''')
            
            conn.commit()
            logger.info(f"Performance database initialized at {self.db_path}")
    
    def record_trade(self, trade: Dict):
        """Record a completed trade"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO trades 
                (symbol, action, entry_price, exit_price, size, pnl, pnl_pct, 
                 ml_confidence, entry_time, exit_time, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.get('symbol'),
                trade.get('action'),
                trade.get('entry_price'),
                trade.get('exit_price'),
                trade.get('size'),
                trade.get('pnl'),
                trade.get('pnl_pct'),
                trade.get('ml_confidence'),
                trade.get('entry_time'),
                trade.get('exit_time', datetime.now().isoformat()),
                trade.get('reason', 'Manual close')
            ))
            conn.commit()
        
        logger.info(f"Trade recorded: {trade.get('symbol')} {trade.get('action')} "
                   f"P&L: {trade.get('pnl_pct', 0):.2f}%")
    
    def record_snapshot(self, snapshot: Dict):
        """Record portfolio snapshot"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO portfolio_snapshots 
                (timestamp, total_value, pnl, pnl_pct, open_positions, total_trades, win_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                snapshot.get('total_value'),
                snapshot.get('pnl'),
                snapshot.get('pnl_pct'),
                snapshot.get('open_positions'),
                snapshot.get('total_trades'),
                snapshot.get('win_rate')
            ))
            conn.commit()
    
    def get_trades(self, limit: int = 100) -> List[Dict]:
        """Get recent trades"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM trades 
                ORDER BY exit_time DESC 
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_performance_chart_data(self, hours: int = 24) -> Dict:
        """Get performance data for charting"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get cumulative P&L over time
            cursor = conn.execute('''
                SELECT 
                    exit_time,
                    pnl,
                    pnl_pct,
                    symbol,
                    SUM(pnl) OVER (ORDER BY exit_time) as cumulative_pnl
                FROM trades 
                WHERE exit_time >= datetime('now', '-' || ? || ' hours')
                ORDER BY exit_time
            ''', (hours,))
            
            trades = [dict(row) for row in cursor.fetchall()]
            
            # Get stats
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    AVG(pnl_pct) as avg_pnl_pct,
                    SUM(pnl) as total_pnl
                FROM trades
                WHERE exit_time >= datetime('now', '-' || ? || ' hours')
            ''', (hours,))
            
            stats = dict(cursor.fetchone())
            stats['win_rate'] = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            
            return {
                'trades': trades,
                'stats': stats
            }
