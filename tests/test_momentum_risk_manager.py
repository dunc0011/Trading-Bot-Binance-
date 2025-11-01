"""
Unit tests for Momentum Risk Manager
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from src.utils.momentum_risk_manager import MomentumRiskManager


class TestMomentumRiskManager:
    """Test cases for MomentumRiskManager"""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        config = Mock()
        config.momentum_position_size_pct = 2.0
        config.max_position_size = 100
        config.momentum_stop_loss_pct = 7.0
        config.momentum_take_profit_pct = 14.0
        config.momentum_max_positions = 3
        return config
    
    def test_position_sizing_2_percent(self, mock_config):
        """Test 2% position sizing"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        balance = 1000  # $1000 USDT
        price = 50
        size = risk_mgr.size_position(price, balance)
        
        assert size == 20.0  # 2% of $1000
    
    def test_position_sizing_respects_cap(self, mock_config):
        """Test position sizing respects MAX_POSITION_SIZE"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        balance = 10000  # $10,000 USDT
        price = 50
        size = risk_mgr.size_position(price, balance)
        
        # 2% of $10,000 = $200, but capped at $100
        assert size == 100.0
    
    def test_stop_loss_and_take_profit(self, mock_config):
        """Test SL/TP calculation"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        entry = 100.0
        sl, tp = risk_mgr.stops_targets(entry)
        
        assert sl == 93.0   # 7% below entry
        assert tp == 114.0  # 14% above entry
    
    def test_trailing_stop_not_activated_early(self, mock_config):
        """Test trailing stop not activated before +7%"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_price': 100.0,
            'stop_loss': 93.0
        }
        
        current_price = 105.0  # +5% (below 7% threshold)
        new_stop = risk_mgr.update_trailing(position, current_price)
        
        assert new_stop is None  # Not activated yet
    
    def test_trailing_stop_activates_at_7_percent(self, mock_config):
        """Test trailing stop activates at +7%"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_price': 100.0,
            'stop_loss': 93.0
        }
        
        current_price = 110.0  # +10%
        new_stop = risk_mgr.update_trailing(position, current_price)
        
        assert new_stop is not None
        assert new_stop > 93.0  # Higher than original stop
        assert new_stop < 110.0  # Below current price
    
    def test_trailing_stop_locks_profit(self, mock_config):
        """Test trailing stop locks in 50% of gains above +7%"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_price': 100.0,
            'stop_loss': 93.0,
            'peak_price': 100.0
        }
        
        # Price hits +10% (+3% above activation threshold)
        current_price = 110.0
        new_stop = risk_mgr.update_trailing(position, current_price)
        
        # Should lock: entry + 7% + (50% of 3%) = entry + 8.5%
        expected_stop = 100.0 * 1.085
        assert abs(new_stop - expected_stop) < 0.1
    
    def test_ttl_not_expired(self, mock_config):
        """Test TTL doesn't trigger before 4 hours"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_time': datetime.now() - timedelta(hours=2),
            'entry_price': 100.0
        }
        
        indicators = {'adx': 30, 'volume_ratio': 1.5, 'current_price': 102.0}
        should_exit = risk_mgr.should_exit_ttl(position, indicators)
        
        assert should_exit == False
    
    def test_ttl_exits_stalling_position(self, mock_config):
        """Test TTL exits position stalling after 4h"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_time': datetime.now() - timedelta(hours=5),
            'entry_price': 100.0
        }
        
        # Position up only +1%, weak momentum
        indicators = {'adx': 20, 'volume_ratio': 0.8, 'current_price': 101.0}
        should_exit = risk_mgr.should_exit_ttl(position, indicators)
        
        assert should_exit == True
    
    def test_ttl_extends_for_winning_position(self, mock_config):
        """Test TTL extends if position is +3% or more"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        position = {
            'entry_time': datetime.now() - timedelta(hours=5),
            'entry_price': 100.0
        }
        
        # Position up +5%, good momentum
        indicators = {'adx': 30, 'volume_ratio': 1.5, 'current_price': 105.0}
        should_exit = risk_mgr.should_exit_ttl(position, indicators)
        
        assert should_exit == False  # Extended
    
    def test_can_open_momentum_position_limit(self, mock_config):
        """Test momentum position limit enforced"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        # Already have 3 momentum positions
        active_positions = {
            'SYM1': {'strategy_type': 'MOMENTUM'},
            'SYM2': {'strategy_type': 'MOMENTUM'},
            'SYM3': {'strategy_type': 'MOMENTUM'},
        }
        
        can_open, reason = risk_mgr.can_open_momentum_position(active_positions)
        assert can_open == False
        assert 'Max momentum positions' in reason
    
    def test_can_open_momentum_position_total_limit(self, mock_config):
        """Test total position limit enforced"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        # 10 total positions (mixed)
        active_positions = {f'SYM{i}': {'strategy_type': 'ML'} for i in range(10)}
        
        can_open, reason = risk_mgr.can_open_momentum_position(active_positions)
        assert can_open == False
        assert 'Total position limit' in reason
    
    def test_risk_level_calculation(self, mock_config):
        """Test risk level classification"""
        risk_mgr = MomentumRiskManager(mock_config)
        
        # Low risk: low ATR, high liquidity, high score
        level = risk_mgr.calculate_risk_level(atr_pct=1.5, liquidity_score=1.0, momentum_score=9.0)
        assert level == 'LOW'
        
        # High risk: high ATR, low liquidity, low score
        level = risk_mgr.calculate_risk_level(atr_pct=5.0, liquidity_score=0.3, momentum_score=5.5)
        assert level == 'HIGH'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
