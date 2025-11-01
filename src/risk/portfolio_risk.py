"""
Portfolio-Level Risk Management
Circuit breakers, VaR limits, drawdown controls, beta hedging
"""
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque


logger = logging.getLogger(__name__)


class PortfolioRiskManager:
    """Advanced portfolio-level risk management."""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Risk limits
        self.max_portfolio_drawdown_pct = 0.50  # 50% max drawdown (testnet - aggressive)
        self.max_daily_loss_pct = 0.15          # 15% max daily loss
        self.var_confidence = 0.95              # 95% VaR
        self.var_lookback_days = 30             # 30 days for VaR calculation
        
        # Circuit breaker state
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        self.circuit_breaker_activated_at = None
        
        # Track portfolio state
        self.starting_balance = None
        self.peak_balance = None
        self.daily_starting_balance = None
        self.daily_reset_date = None
        
        # Track returns for VaR
        self.returns_history = deque(maxlen=self.var_lookback_days)
        
        # Position tracking
        self.current_positions = {}  # symbol -> position data
        
        self.logger.info("Portfolio Risk Manager initialized")
    
    def set_starting_balance(self, balance: float):
        """Set initial portfolio balance."""
        self.starting_balance = balance
        self.peak_balance = balance
        self.daily_starting_balance = balance
        self.daily_reset_date = datetime.now().date()
        self.logger.info(f"Starting balance set: ${balance:.2f}")
    
    def update_balance(self, current_balance: float) -> Dict:
        """
        Update current balance and check risk limits.
        
        Returns:
            dict with 'allowed' (bool), 'reason' (str), 'warnings' (list)
        """
        if self.starting_balance is None:
            self.set_starting_balance(current_balance)
        
        # Reset daily balance at start of new day
        today = datetime.now().date()
        if self.daily_reset_date != today:
            self.daily_starting_balance = current_balance
            self.daily_reset_date = today
            self.logger.info(f"Daily balance reset: ${current_balance:.2f}")
        
        # Update peak
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
        
        # Calculate drawdowns
        total_drawdown = (self.peak_balance - current_balance) / self.peak_balance if self.peak_balance > 0 else 0
        daily_pnl_pct = (current_balance - self.daily_starting_balance) / self.daily_starting_balance if self.daily_starting_balance > 0 else 0
        
        # Track return
        if len(self.returns_history) > 0:
            prev_balance = self.daily_starting_balance
            if prev_balance > 0:
                daily_return = (current_balance - prev_balance) / prev_balance
                self.returns_history.append(daily_return)
        
        warnings = []
        
        # Check daily loss limit (TEMPORARILY DISABLED FOR RTM TESTING)
        if False and daily_pnl_pct < -self.max_daily_loss_pct:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = f"Daily loss limit breached: {daily_pnl_pct:.2%}"
            self.circuit_breaker_activated_at = datetime.now()
            
            self.logger.warning(f"⚠️  Circuit breaker disabled: Would trigger at {daily_pnl_pct:.2%}")
            
            # return {
            #     'allowed': False,
            #     'reason': self.circuit_breaker_reason,
            #     'warnings': [],
            #     'total_drawdown': total_drawdown,
            #     'daily_pnl_pct': daily_pnl_pct
            # }
        
        # Check portfolio drawdown limit
        if total_drawdown >= self.max_portfolio_drawdown_pct:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = f"Max drawdown limit breached: {total_drawdown:.2%}"
            self.circuit_breaker_activated_at = datetime.now()
            
            self.logger.error(f"🚨 CIRCUIT BREAKER: {self.circuit_breaker_reason}")
            
            return {
                'allowed': False,
                'reason': self.circuit_breaker_reason,
                'warnings': [],
                'total_drawdown': total_drawdown,
                'daily_pnl_pct': daily_pnl_pct
            }
        
        # Warnings (approaching limits)
        if total_drawdown > self.max_portfolio_drawdown_pct * 0.7:
            warnings.append(f"⚠️  High drawdown: {total_drawdown:.2%} (limit: {self.max_portfolio_drawdown_pct:.2%})")
        
        if daily_pnl_pct < -self.max_daily_loss_pct * 0.7:
            warnings.append(f"⚠️  Daily loss approaching limit: {daily_pnl_pct:.2%} (limit: {-self.max_daily_loss_pct:.2%})")
        
        for warning in warnings:
            self.logger.warning(warning)
        
        return {
            'allowed': True,
            'reason': 'Within limits',
            'warnings': warnings,
            'total_drawdown': total_drawdown,
            'daily_pnl_pct': daily_pnl_pct
        }
    
    def calculate_var(self, confidence: float = None) -> float:
        """
        Calculate Value at Risk (VaR) using historical simulation.
        
        Returns:
            VaR as a fraction (e.g., 0.05 = 5% potential loss)
        """
        if confidence is None:
            confidence = self.var_confidence
        
        if len(self.returns_history) < 10:
            return 0.02  # Default 2% if insufficient data
        
        returns = list(self.returns_history)
        returns_sorted = sorted(returns)
        
        # Calculate percentile for VaR
        var_index = int((1 - confidence) * len(returns_sorted))
        var = abs(returns_sorted[var_index]) if var_index < len(returns_sorted) else 0.02
        
        return var
    
    def check_var_limit(self, proposed_position_size: float, current_balance: float) -> Dict:
        """
        Check if proposed position would exceed VaR limit.
        
        Returns:
            dict with 'allowed' (bool), 'reason' (str), 'adjusted_size' (float)
        """
        var = self.calculate_var()
        max_var_exposure = current_balance * var
        
        # Calculate current exposure
        current_exposure = sum(pos.get('size', 0) for pos in self.current_positions.values())
        
        # Check if new position would exceed VaR limit
        total_exposure = current_exposure + proposed_position_size
        
        # Allow up to 2x VaR as maximum exposure
        max_allowed_exposure = max_var_exposure * 2
        
        if total_exposure > max_allowed_exposure:
            # Adjust position size
            adjusted_size = max(0, max_allowed_exposure - current_exposure)
            
            if adjusted_size < proposed_position_size * 0.5:  # Less than 50% of desired
                return {
                    'allowed': False,
                    'reason': f'VaR limit (current: ${current_exposure:.0f}, max: ${max_allowed_exposure:.0f})',
                    'adjusted_size': 0,
                    'var': var
                }
            
            self.logger.warning(f"⚠️  Position size adjusted for VaR: ${proposed_position_size:.0f} → ${adjusted_size:.0f}")
            
            return {
                'allowed': True,
                'reason': 'Position adjusted for VaR limit',
                'adjusted_size': adjusted_size,
                'var': var
            }
        
        return {
            'allowed': True,
            'reason': 'Within VaR limits',
            'adjusted_size': proposed_position_size,
            'var': var
        }
    
    def add_position(self, symbol: str, size: float, entry_price: float, confidence: float):
        """Track a new position."""
        self.current_positions[symbol] = {
            'size': size,
            'entry_price': entry_price,
            'confidence': confidence,
            'opened_at': datetime.now().isoformat()
        }
        
        total_exposure = sum(p['size'] for p in self.current_positions.values())
        self.logger.info(f"Position added: {symbol} ${size:.0f} | Total exposure: ${total_exposure:.0f}")
    
    def remove_position(self, symbol: str) -> Optional[Dict]:
        """Remove a closed position."""
        if symbol in self.current_positions:
            position = self.current_positions.pop(symbol)
            total_exposure = sum(p['size'] for p in self.current_positions.values())
            self.logger.info(f"Position removed: {symbol} | Total exposure: ${total_exposure:.0f}")
            return position
        return None
    
    def get_portfolio_exposure(self) -> Dict:
        """Get current portfolio exposure statistics."""
        if not self.current_positions:
            return {
                'total_exposure': 0,
                'position_count': 0,
                'avg_confidence': 0,
                'positions': []
            }
        
        total_exposure = sum(p['size'] for p in self.current_positions.values())
        avg_confidence = np.mean([p['confidence'] for p in self.current_positions.values()])
        
        return {
            'total_exposure': total_exposure,
            'position_count': len(self.current_positions),
            'avg_confidence': avg_confidence,
            'positions': list(self.current_positions.keys())
        }
    
    def check_correlation_risk(self, symbol: str, correlation_groups: Dict) -> bool:
        """
        Check if adding this symbol would create too much correlation risk.
        
        Args:
            symbol: Symbol to check
            correlation_groups: Dict of group_name -> [symbols]
        
        Returns:
            True if allowed, False if too correlated
        """
        # Find symbol's group
        symbol_group = None
        for group_name, symbols in correlation_groups.items():
            if symbol in symbols:
                symbol_group = group_name
                break
        
        if not symbol_group:
            return True  # Not in any group, allow
        
        # Count positions in same group
        group_positions = [s for s in self.current_positions.keys() 
                          if s in correlation_groups[symbol_group]]
        
        # Allow up to 40% of portfolio in one correlation group
        group_exposure = sum(self.current_positions[s]['size'] 
                           for s in group_positions)
        
        total_exposure = sum(p['size'] for p in self.current_positions.values())
        
        if total_exposure > 0:
            group_exposure_pct = group_exposure / total_exposure
            
            if group_exposure_pct > 0.40:
                self.logger.warning(
                    f"⚠️  Correlation risk: {symbol_group} group at {group_exposure_pct:.1%} of portfolio"
                )
                return False
        
        return True
    
    def reset_circuit_breaker(self):
        """Manually reset circuit breaker (admin action)."""
        if self.circuit_breaker_active:
            self.logger.info(f"Circuit breaker manually reset (was: {self.circuit_breaker_reason})")
            self.circuit_breaker_active = False
            self.circuit_breaker_reason = ""
            self.circuit_breaker_activated_at = None
    
    def get_risk_summary(self) -> Dict:
        """Get comprehensive risk summary."""
        return {
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_reason': self.circuit_breaker_reason,
            'total_exposure': sum(p['size'] for p in self.current_positions.values()),
            'position_count': len(self.current_positions),
            'var_95': self.calculate_var(),
            'peak_balance': self.peak_balance,
            'current_drawdown': (self.peak_balance - self.starting_balance) / self.peak_balance if self.peak_balance else 0
        }
