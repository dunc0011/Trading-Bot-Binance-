"""
Trade Feedback Database System
Captures every trade with full market context for adaptive learning
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd


class TradeLogger:
    """
    Comprehensive trade logging system for adaptive learning
    Stores every trade with entry/exit features, market context, and outcomes
    """
    
    def __init__(self, db_path: str = 'data/adaptive_learning.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    symbol TEXT NOT NULL,
                    
                    -- Trade Basic Info
                    action TEXT NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    exit_time TIMESTAMP,
                    duration_seconds INTEGER,
                    
                    -- Prices & PnL
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    position_size REAL NOT NULL,
                    profit_usd REAL,
                    profit_pct REAL,
                    fees_paid REAL DEFAULT 0,
                    entry_is_maker INTEGER DEFAULT 0,  -- 1 if maker order, 0 if taker
                    exit_is_maker INTEGER DEFAULT 0,   -- 1 if maker order, 0 if taker
                    spread_bps REAL,                    -- Spread at entry in basis points
                    outcome TEXT,  -- WIN, LOSS, BREAKEVEN
                    
                    -- ML Signal Info
                    ml_confidence REAL,
                    signal_strength REAL,
                    model_version TEXT,
                    
                    -- Market Context at Entry
                    regime_trending INTEGER,
                    regime_ranging INTEGER,
                    regime_volatile INTEGER,
                    h1_trend INTEGER,
                    trend_confluence INTEGER,
                    
                    -- Volume Context
                    volume_surge REAL,
                    buy_sell_ratio REAL,
                    vwap_distance REAL,
                    
                    -- Technical Indicators at Entry
                    rsi REAL,
                    adx REAL,
                    atr_pct REAL,
                    
                    -- Exit Reason
                    exit_reason TEXT,  -- TP1, TP2, STOP_LOSS, TRAILING, MANUAL
                    
                    -- Full Feature Snapshot (JSON)
                    entry_features TEXT,  -- JSON of all features
                    exit_features TEXT,   -- JSON of all features at exit
                    
                    -- Meta Information
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                )
            """)
            
            # Create indexes for fast queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON trades(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome ON trades(outcome)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entry_time ON trades(entry_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_confidence ON trades(ml_confidence)")
            
            # Model performance tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    trained_at TIMESTAMP NOT NULL,
                    accuracy REAL,
                    f1_score REAL,
                    trades_seen INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_profit REAL DEFAULT 0,
                    win_rate REAL,
                    avg_profit REAL,
                    is_active BOOLEAN DEFAULT 1,
                    notes TEXT
                )
            """)
            
            # Learning events log
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,  -- ONLINE_UPDATE, META_RETRAIN, RL_UPDATE
                    symbol TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    before_metric REAL,
                    after_metric REAL,
                    trades_processed INTEGER,
                    details TEXT,
                    success BOOLEAN DEFAULT 1
                )
            """)
            
            conn.commit()
            self.logger.info(f"Trade logging database initialized: {self.db_path}")
    
    def log_trade(self, trade_data: Dict):
        """
        Log a completed trade with full context
        
        Args:
            trade_data: Dict containing all trade information
        """
        with sqlite3.connect(self.db_path) as conn:
            # Determine outcome
            profit_pct = trade_data.get('profit_pct', 0)
            if profit_pct > 0.1:
                outcome = 'WIN'
            elif profit_pct < -0.1:
                outcome = 'LOSS'
            else:
                outcome = 'BREAKEVEN'
            
            # Serialize feature dictionaries to JSON
            entry_features_json = json.dumps(trade_data.get('entry_features', {}))
            exit_features_json = json.dumps(trade_data.get('exit_features', {}))
            
            conn.execute("""
                INSERT OR REPLACE INTO trades (
                    trade_id, symbol, action, entry_time, exit_time, duration_seconds,
                    entry_price, exit_price, position_size, profit_usd, profit_pct, fees_paid, outcome,
                    ml_confidence, signal_strength, model_version,
                    regime_trending, regime_ranging, regime_volatile, h1_trend, trend_confluence,
                    volume_surge, buy_sell_ratio, vwap_distance,
                    rsi, adx, atr_pct,
                    exit_reason, entry_features, exit_features, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data.get('trade_id', f"{trade_data['symbol']}_{int(datetime.now().timestamp())}"),
                trade_data['symbol'],
                trade_data.get('action', 'BUY'),
                trade_data.get('entry_time'),
                trade_data.get('exit_time'),
                trade_data.get('duration_seconds'),
                trade_data['entry_price'],
                trade_data.get('exit_price'),
                trade_data['position_size'],
                trade_data.get('profit_usd'),
                trade_data.get('profit_pct'),
                trade_data.get('fees_paid', 0),
                outcome,
                trade_data.get('ml_confidence'),
                trade_data.get('signal_strength'),
                trade_data.get('model_version'),
                trade_data.get('regime_trending', 0),
                trade_data.get('regime_ranging', 0),
                trade_data.get('regime_volatile', 0),
                trade_data.get('h1_trend', 0),
                trade_data.get('trend_confluence', 0),
                trade_data.get('volume_surge'),
                trade_data.get('buy_sell_ratio'),
                trade_data.get('vwap_distance'),
                trade_data.get('rsi'),
                trade_data.get('adx'),
                trade_data.get('atr_pct'),
                trade_data.get('exit_reason'),
                entry_features_json,
                exit_features_json,
                trade_data.get('notes')
            ))
            
            conn.commit()
            self.logger.info(f"Logged trade: {trade_data['symbol']} {outcome} ({profit_pct:+.2f}%)")
    
    def log_learning_event(self, event_type: str, symbol: Optional[str], 
                          before_metric: float, after_metric: float, 
                          trades_processed: int, details: str = None):
        """Log a learning/training event"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO learning_events (event_type, symbol, before_metric, after_metric, trades_processed, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_type, symbol, before_metric, after_metric, trades_processed, details))
            conn.commit()
    
    def get_recent_trades(self, limit: int = 100, symbol: Optional[str] = None) -> pd.DataFrame:
        """Get recent trades for analysis"""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM trades"
            if symbol:
                query += f" WHERE symbol = '{symbol}'"
            query += f" ORDER BY entry_time DESC LIMIT {limit}"
            
            return pd.read_sql_query(query, conn)
    
    def get_trades_for_learning(self, min_trades: int = 10, 
                                confidence_range: tuple = (0.55, 0.75)) -> pd.DataFrame:
        """Get trades suitable for online learning"""
        with sqlite3.connect(self.db_path) as conn:
            query = """
                SELECT * FROM trades 
                WHERE ml_confidence BETWEEN ? AND ?
                AND exit_time IS NOT NULL
                ORDER BY entry_time DESC
                LIMIT ?
            """
            return pd.read_sql_query(query, conn, params=(*confidence_range, min_trades * 10))
    
    def get_win_rate_by_context(self) -> Dict:
        """Analyze win rate by various contexts"""
        with sqlite3.connect(self.db_path) as conn:
            results = {}
            
            # By confidence level
            df = pd.read_sql_query("""
                SELECT 
                    CASE 
                        WHEN ml_confidence < 0.60 THEN '50-60%'
                        WHEN ml_confidence < 0.65 THEN '60-65%'
                        WHEN ml_confidence < 0.70 THEN '65-70%'
                        ELSE '70%+'
                    END as conf_range,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    AVG(profit_pct) as avg_profit
                FROM trades
                WHERE exit_time IS NOT NULL
                GROUP BY conf_range
            """, conn)
            results['by_confidence'] = df.to_dict('records')
            
            # By regime
            df = pd.read_sql_query("""
                SELECT 
                    CASE 
                        WHEN regime_trending = 1 THEN 'Trending'
                        WHEN regime_ranging = 1 THEN 'Ranging'
                        WHEN regime_volatile = 1 THEN 'Volatile'
                        ELSE 'Unknown'
                    END as regime,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    AVG(profit_pct) as avg_profit
                FROM trades
                WHERE exit_time IS NOT NULL
                GROUP BY regime
            """, conn)
            results['by_regime'] = df.to_dict('records')
            
            # By trend confluence
            df = pd.read_sql_query("""
                SELECT 
                    CASE 
                        WHEN trend_confluence = 1 THEN 'Aligned'
                        WHEN trend_confluence = -1 THEN 'Divergent'
                        ELSE 'Neutral'
                    END as confluence,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    AVG(profit_pct) as avg_profit
                FROM trades
                WHERE exit_time IS NOT NULL
                GROUP BY confluence
            """, conn)
            results['by_confluence'] = df.to_dict('records')
            
            return results
    
    def get_stats(self) -> Dict:
        """Get overall statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN outcome = 'BREAKEVEN' THEN 1 ELSE 0 END) as breakeven,
                    AVG(profit_pct) as avg_profit_pct,
                    SUM(profit_usd) as total_profit_usd,
                    AVG(ml_confidence) as avg_confidence,
                    AVG(duration_seconds) / 60.0 as avg_duration_minutes
                FROM trades
                WHERE exit_time IS NOT NULL
            """)
            row = cursor.fetchone()
            
            if row and row[0] > 0:
                return {
                    'total_trades': row[0],
                    'wins': row[1] or 0,
                    'losses': row[2] or 0,
                    'breakeven': row[3] or 0,
                    'win_rate': (row[1] or 0) / row[0] * 100 if row[0] > 0 else 0,
                    'avg_profit_pct': row[4] or 0,
                    'total_profit_usd': row[5] or 0,
                    'avg_confidence': row[6] or 0,
                    'avg_duration_minutes': row[7] or 0
                }
            else:
                return {
                    'total_trades': 0,
                    'wins': 0,
                    'losses': 0,
                    'breakeven': 0,
                    'win_rate': 0,
                    'avg_profit_pct': 0,
                    'total_profit_usd': 0,
                    'avg_confidence': 0,
                    'avg_duration_minutes': 0
                }
