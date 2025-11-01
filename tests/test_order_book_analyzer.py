"""
Unit tests for Order Book Analyzer
"""
import pytest
from unittest.mock import Mock, MagicMock
from src.utils.order_book_analyzer import OrderBookAnalyzer


class TestOrderBookAnalyzer:
    """Test cases for OrderBookAnalyzer"""
    
    def test_compute_depth_within_1_percent(self):
        """Test liquidity calculation within 1% of mid price"""
        # Mock client
        mock_client = Mock()
        
        # Create synthetic order book
        # Mid price = 100, so 1% range is 99-101
        mock_client.get_order_book.return_value = {
            'bids': [
                ['100.0', '500'],    # $50,000
                ['99.5', '300'],     # $29,850
                ['99.0', '200'],     # $19,800  (total: $99,650)
                ['98.0', '100'],     # Out of range
            ],
            'asks': [
                ['100.0', '400'],    # $40,000
                ['100.5', '250'],    # $25,125
                ['101.0', '300'],    # $30,300  (total: $95,425)
                ['102.0', '100'],    # Out of range
            ]
        }
        
        analyzer = OrderBookAnalyzer(mock_client)
        result = analyzer.compute_depth_within_pct('TESTUSDT', pct=0.01)
        
        assert 'bid_usdt' in result
        assert 'ask_usdt' in result
        assert result['mid'] == 100.0
        assert result['bid_usdt'] > 99000  # Should be ~$99,650
        assert result['ask_usdt'] > 95000  # Should be ~$95,425
    
    def test_is_liquid_passes(self):
        """Test liquidity check passes with sufficient depth"""
        mock_client = Mock()
        mock_client.get_order_book.return_value = {
            'bids': [['100.0', '600']],   # $60,000
            'asks': [['100.0', '600']]    # $60,000
        }
        
        analyzer = OrderBookAnalyzer(mock_client)
        is_liquid, info = analyzer.is_liquid('TESTUSDT', min_each_side=50000)
        
        assert is_liquid == True
        assert info['bid_usdt'] >= 50000
        assert info['ask_usdt'] >= 50000
    
    def test_is_liquid_fails_thin_bids(self):
        """Test liquidity check fails with thin bid side"""
        mock_client = Mock()
        mock_client.get_order_book.return_value = {
            'bids': [['100.0', '300']],   # $30,000 (insufficient)
            'asks': [['100.0', '600']]    # $60,000 (sufficient)
        }
        
        analyzer = OrderBookAnalyzer(mock_client)
        is_liquid, info = analyzer.is_liquid('TESTUSDT', min_each_side=50000)
        
        assert is_liquid == False
        assert info['bid_usdt'] < 50000
    
    def test_is_liquid_fails_thin_asks(self):
        """Test liquidity check fails with thin ask side"""
        mock_client = Mock()
        mock_client.get_order_book.return_value = {
            'bids': [['100.0', '600']],   # $60,000 (sufficient)
            'asks': [['100.0', '200']]    # $20,000 (insufficient)
        }
        
        analyzer = OrderBookAnalyzer(mock_client)
        is_liquid, info = analyzer.is_liquid('TESTUSDT', min_each_side=50000)
        
        assert is_liquid == False
        assert info['ask_usdt'] < 50000
    
    def test_handles_api_error_gracefully(self):
        """Test error handling when API fails"""
        mock_client = Mock()
        mock_client.get_order_book.side_effect = Exception("API Error")
        
        analyzer = OrderBookAnalyzer(mock_client)
        result = analyzer.compute_depth_within_pct('TESTUSDT')
        
        assert result['bid_usdt'] == 0
        assert result['ask_usdt'] == 0
        assert 'error' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
