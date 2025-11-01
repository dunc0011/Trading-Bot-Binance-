"""
Adaptive Parameter Tuner - Self-Optimizing Trading Parameters

Automatically adjusts:
- Per-symbol confidence thresholds
- Position sizing multipliers
- Stop-loss/take-profit levels
- Trading hour filters

Based on recent performance data.
"""
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from analytics.pattern_analyzer import PatternAnalyzer

logger = logging.getLogger(__name__)


class AdaptiveParameterTuner:
    """Automatically tunes trading parameters based on performance."""
    
    def __init__(self, db_path: str = 'data/performance.db'):
        self.db_path = db_path
        self.pattern_analyzer = PatternAnalyzer(db_path)
        self.parameters = {}
        self.last_update = None
        self.update_interval_hours = 6  # Re-tune every 6 hours
        
        # Load saved parameters
        self._load_parameters()
    
    def get_parameters(self, symbol: str) -> Dict:
        """
        Get adaptive parameters for a symbol.
        
        Returns dict with:
        - confidence_threshold_adjust: +/- adjustment to base threshold
        - position_size_multiplier: Scale factor for position size
        - preferred_hours: List of best hours to trade (or None for any time)
        - recommendation: PREFERRED, NEUTRAL, or AVOID
        """
        # Check if we need to update
        if self._should_update():
            self.update_all_parameters()
        
        # Return cached parameters or defaults
        return self.parameters.get(symbol, self._get_default_parameters())
    
    def update_all_parameters(self):
        """Re-analyze patterns and update all parameters."""
        logger.info("🔧 Updating adaptive parameters...")
        
        try:
            # Run pattern analysis
            insights = self.pattern_analyzer.analyze_all(min_trades=15)
            
            # Update parameters for each symbol
            for symbol in insights['by_symbol'].keys():
                self.parameters[symbol] = self._calculate_symbol_parameters(symbol, insights)
            
            # Save parameters
            self._save_parameters()
            self.last_update = datetime.now()
            
            logger.info(f"✅ Updated parameters for {len(self.parameters)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to update parameters: {e}", exc_info=True)
    
    def _calculate_symbol_parameters(self, symbol: str, insights: Dict) -> Dict:
        """Calculate optimal parameters for a specific symbol."""
        symbol_data = insights['by_symbol'].get(symbol, {})
        
        if not symbol_data:
            return self._get_default_parameters()
        
        # Extract metrics
        win_rate = symbol_data.get('win_rate', 0.5)
        avg_pnl = symbol_data.get('avg_pnl_pct', 0)
        quality_score = symbol_data.get('quality_score', 0.5)
        trade_count = symbol_data.get('trade_count', 0)
        
        # Adaptive confidence threshold adjustment
        # High performers: lower threshold (take more trades)
        # Low performers: raise threshold (be more selective)
        if quality_score > 0.7 and win_rate > 0.60:
            conf_adjust = -0.03  # Lower by 3%
            recommendation = 'PREFERRED'
        elif quality_score > 0.5 and win_rate > 0.52:
            conf_adjust = -0.01  # Lower by 1%
            recommendation = 'NEUTRAL'
        elif quality_score < 0.3 or win_rate < 0.45:
            conf_adjust = +0.05  # Raise by 5%
            recommendation = 'AVOID'
        else:
            conf_adjust = 0
            recommendation = 'NEUTRAL'
        
        # Adaptive position sizing
        # Scale position size based on recent performance
        if avg_pnl > 0.5 and win_rate > 0.60:
            size_multiplier = 1.3  # 30% larger
        elif avg_pnl > 0.2 and win_rate > 0.55:
            size_multiplier = 1.15  # 15% larger
        elif avg_pnl < -0.2 or win_rate < 0.45:
            size_multiplier = 0.6  # 40% smaller
        elif avg_pnl < 0 or win_rate < 0.50:
            size_multiplier = 0.8  # 20% smaller
        else:
            size_multiplier = 1.0
        
        # Get best trading hours
        preferred_hours = self.pattern_analyzer.get_best_trading_hours(top_n=6)
        
        return {
            'symbol': symbol,
            'confidence_threshold_adjust': conf_adjust,
            'position_size_multiplier': size_multiplier,
            'preferred_hours': preferred_hours if len(preferred_hours) > 0 else None,
            'recommendation': recommendation,
            'win_rate': win_rate,
            'avg_pnl_pct': avg_pnl,
            'quality_score': quality_score,
            'trade_count': trade_count,
            'updated_at': datetime.now().isoformat()
        }
    
    def should_trade_now(self, symbol: str) -> bool:
        """
        Check if current time is optimal for trading this symbol.
        
        Returns True if:
        - No preferred hours set (trade anytime), OR
        - Current hour is in preferred hours list
        """
        params = self.get_parameters(symbol)
        preferred_hours = params.get('preferred_hours')
        
        if not preferred_hours:
            return True  # No time restrictions
        
        current_hour = datetime.now().hour
        return current_hour in preferred_hours
    
    def adjust_confidence_threshold(self, symbol: str, base_threshold: float) -> float:
        """Apply adaptive adjustment to confidence threshold."""
        params = self.get_parameters(symbol)
        adjust = params.get('confidence_threshold_adjust', 0)
        adjusted = base_threshold + adjust
        
        # Clamp to reasonable range
        return max(0.50, min(0.95, adjusted))
    
    def adjust_position_size(self, symbol: str, base_size: float) -> float:
        """Apply adaptive scaling to position size."""
        params = self.get_parameters(symbol)
        multiplier = params.get('position_size_multiplier', 1.0)
        return base_size * multiplier
    
    def _should_update(self) -> bool:
        """Check if parameters should be re-calculated."""
        if self.last_update is None:
            return True
        
        elapsed = datetime.now() - self.last_update
        return elapsed.total_seconds() > (self.update_interval_hours * 3600)
    
    def _get_default_parameters(self) -> Dict:
        """Return default parameters for symbols with no data."""
        return {
            'confidence_threshold_adjust': 0,
            'position_size_multiplier': 1.0,
            'preferred_hours': None,
            'recommendation': 'NEUTRAL',
            'win_rate': 0.5,
            'avg_pnl_pct': 0,
            'quality_score': 0.5,
            'trade_count': 0,
            'updated_at': datetime.now().isoformat()
        }
    
    def _load_parameters(self):
        """Load saved parameters from disk."""
        param_file = Path('data/adaptive_parameters.json')
        if param_file.exists():
            try:
                with open(param_file, 'r') as f:
                    data = json.load(f)
                    self.parameters = data.get('parameters', {})
                    last_update_str = data.get('last_update')
                    if last_update_str:
                        self.last_update = datetime.fromisoformat(last_update_str)
                logger.info(f"📥 Loaded parameters for {len(self.parameters)} symbols")
            except Exception as e:
                logger.error(f"Failed to load parameters: {e}")
    
    def _save_parameters(self):
        """Save current parameters to disk."""
        try:
            param_file = Path('data/adaptive_parameters.json')
            param_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'parameters': self.parameters,
                'last_update': self.last_update.isoformat() if self.last_update else None,
                'update_interval_hours': self.update_interval_hours
            }
            
            with open(param_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"💾 Saved parameters for {len(self.parameters)} symbols")
        except Exception as e:
            logger.error(f"Failed to save parameters: {e}")
    
    def get_top_performers(self, top_n: int = 10) -> list:
        """Get top N performing symbols for priority trading."""
        sorted_symbols = sorted(
            self.parameters.items(),
            key=lambda x: (x[1].get('quality_score', 0), x[1].get('win_rate', 0)),
            reverse=True
        )
        
        return [
            {
                'symbol': sym,
                'quality_score': params['quality_score'],
                'win_rate': params['win_rate'],
                'avg_pnl_pct': params['avg_pnl_pct']
            }
            for sym, params in sorted_symbols[:top_n]
        ]
    
    def get_recommendation_summary(self) -> Dict:
        """Get summary of recommendations across all symbols."""
        recommendations = {'PREFERRED': 0, 'NEUTRAL': 0, 'AVOID': 0}
        
        for params in self.parameters.values():
            rec = params.get('recommendation', 'NEUTRAL')
            recommendations[rec] = recommendations.get(rec, 0) + 1
        
        return {
            'total_symbols': len(self.parameters),
            'recommendations': recommendations,
            'last_update': self.last_update.isoformat() if self.last_update else None
        }
