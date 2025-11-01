"""
Persistent Position Tracker - Remembers positions across bot restarts
"""
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PositionTracker:
    """Track open positions in SQLite database for persistence across restarts"""
    
    def __init__(self, db_path: str = 'data/positions.db'):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                size REAL NOT NULL,
                ml_confidence REAL,
                metadata TEXT,
                updated_at TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Position tracker initialized: {self.db_path}")
    
    def save_position(self, symbol: str, entry_price: float, size: float, 
                     ml_confidence: float = 0, metadata: Dict = None):
        """Save or update a position"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {})
        
        cursor.execute('''
            INSERT OR REPLACE INTO positions 
            (symbol, entry_price, entry_time, size, ml_confidence, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, entry_price, now, size, ml_confidence, metadata_json, now))
        
        conn.commit()
        conn.close()
        logger.info(f"💾 Saved position: {symbol} @ ${entry_price:.2f}, size=${size:.2f}")
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get position data for a symbol"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT entry_price, entry_time, size, ml_confidence, metadata
            FROM positions WHERE symbol = ?
        ''', (symbol,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'entry_price': row[0],
                'entry_time': row[1],
                'size': row[2],
                'ml_confidence': row[3],
                'metadata': json.loads(row[4]) if row[4] else {}
            }
        return None
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all open positions"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, entry_price, entry_time, size, ml_confidence, metadata
            FROM positions
        ''')
        
        positions = {}
        for row in cursor.fetchall():
            positions[row[0]] = {
                'entry_price': row[1],
                'entry_time': row[2],
                'size': row[3],
                'ml_confidence': row[4],
                'metadata': json.loads(row[5]) if row[5] else {}
            }
        
        conn.close()
        return positions
    
    def remove_position(self, symbol: str):
        """Remove a position when closed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM positions WHERE symbol = ?', (symbol,))
        
        conn.commit()
        conn.close()
        logger.info(f"🗑️  Removed position: {symbol}")
    
    def clear_all(self):
        """Clear all positions (use with caution)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM positions')
        
        conn.commit()
        conn.close()
        logger.warning("⚠️  Cleared all positions from tracker")
