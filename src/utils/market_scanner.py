"""
Multi-Pair Market Scanner
Scans all USDT pairs and ranks by ML prediction scores
"""
import logging
from typing import List, Dict
from datetime import datetime
import pandas as pd


class MarketScanner:
    """Scans multiple trading pairs and ranks by ML predictions"""
    
    def __init__(self, client, ml_manager, config, logger=None):
        self.client = client
        self.ml_manager = ml_manager
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Scanner settings
        self.base_asset = 'USDT'
        self.min_volume_24h = float(getattr(config, 'min_volume_24h', 1000000))  # $1M default
        self.max_pairs = int(getattr(config, 'max_trading_pairs', 5))
        self.excluded_pairs = getattr(config, 'excluded_pairs', '').split(',')
        
        self.all_pairs = []
        self.filtered_pairs = []
        self.last_scan_time = None
    
    def fetch_all_usdt_pairs(self) -> List[str]:
        """Fetch all trading pairs with USDT as quote asset"""
        try:
            exchange_info = self.client.get_exchange_info()
            
            pairs = []
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol']
                
                # Check if USDT pair and trading
                if (symbol_info['quoteAsset'] == self.base_asset and 
                    symbol_info['status'] == 'TRADING' and
                    symbol not in self.excluded_pairs):
                    pairs.append(symbol)
            
            self.all_pairs = pairs
            self.logger.info(f"Found {len(pairs)} {self.base_asset} pairs")
            return pairs
        
        except Exception as e:
            self.logger.error(f"Failed to fetch pairs: {e}")
            return []
    
    def filter_by_volume(self, pairs: List[str]) -> List[Dict]:
        """Filter pairs by 24h volume and get additional info"""
        try:
            tickers = self.client.get_ticker()
            
            filtered = []
            for ticker in tickers:
                symbol = ticker['symbol']
                
                if symbol not in pairs:
                    continue
                
                volume_usdt = float(ticker['quoteVolume'])
                
                if volume_usdt >= self.min_volume_24h:
                    filtered.append({
                        'symbol': symbol,
                        'volume_24h': volume_usdt,
                        'price': float(ticker['lastPrice']),
                        'price_change_pct': float(ticker['priceChangePercent']),
                        'high_24h': float(ticker['highPrice']),
                        'low_24h': float(ticker['lowPrice']),
                    })
            
            # Sort by volume
            filtered.sort(key=lambda x: x['volume_24h'], reverse=True)
            
            self.logger.info(f"Filtered to {len(filtered)} pairs by volume (min ${self.min_volume_24h:,.0f})")
            self.filtered_pairs = filtered
            return filtered
        
        except Exception as e:
            self.logger.error(f"Failed to filter by volume: {e}")
            return []
    
    def analyze_pair_with_ml(self, symbol: str) -> Dict:
        """
        Analyze a single pair with ML model
        
        Returns:
            Dict with ML prediction and confidence
        """
        try:
            # Fetch recent klines
            klines = self.client.get_klines(
                symbol=symbol,
                interval=self.config.timeframe,
                limit=200
            )
            
            # Convert to DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            # Build features
            X, _ = self.ml_manager.build_features(df)
            
            if X.empty:
                return {'signal': 0, 'confidence': 0, 'error': 'Insufficient data'}
            
            # Get latest features
            latest_features = X.iloc[[-1]]
            
            # Get ML prediction
            signal = self.ml_manager.predict_signal(latest_features)
            
            # Get probability if available
            confidence = 0.5
            if hasattr(self.ml_manager._model, 'predict_proba'):
                proba = self.ml_manager._model.predict_proba(latest_features)[0]
                confidence = float(proba[1] if signal == 1 else proba[0])
            
            return {
                'signal': signal,
                'confidence': confidence,
                'features': {
                    'ema5': float(latest_features['ema5'].iloc[0]),
                    'ema8': float(latest_features['ema8'].iloc[0]),
                    'rsi': float(latest_features['rsi'].iloc[0]),
                }
            }
        
        except Exception as e:
            self.logger.error(f"ML analysis failed for {symbol}: {e}")
            return {'signal': 0, 'confidence': 0, 'error': str(e)}
    
    def scan_market(self) -> List[Dict]:
        """
        Perform full market scan
        
        Returns:
            List of pairs with ML scores, sorted by signal strength
        """
        self.logger.info("Starting market scan...")
        self.last_scan_time = datetime.now()
        
        # Step 1: Fetch all pairs
        all_pairs = self.fetch_all_usdt_pairs()
        if not all_pairs:
            return []
        
        # Step 2: Filter by volume
        filtered_pairs = self.filter_by_volume(all_pairs)
        if not filtered_pairs:
            return []
        
        # Step 3: Analyze top pairs with ML (limit to prevent API overuse)
        scan_limit = min(50, len(filtered_pairs))  # Analyze top 50 by volume
        results = []
        
        for i, pair_info in enumerate(filtered_pairs[:scan_limit]):
            symbol = pair_info['symbol']
            
            self.logger.info(f"Scanning {i+1}/{scan_limit}: {symbol}")
            
            # ML analysis
            ml_result = self.analyze_pair_with_ml(symbol)
            
            # Combine results
            results.append({
                **pair_info,
                **ml_result,
                'rank': i + 1,
                'scan_time': self.last_scan_time.isoformat()
            })
        
        # Sort by ML signal confidence
        results.sort(key=lambda x: (x['signal'], x['confidence']), reverse=True)
        
        # Re-rank after sorting
        for i, result in enumerate(results):
            result['rank'] = i + 1
        
        self.logger.info(f"Scan complete. Found {sum(1 for r in results if r['signal'] == 1)} buy signals")
        return results
    
    def get_top_opportunities(self, n=5) -> List[Dict]:
        """Get top N trading opportunities from last scan"""
        if not self.filtered_pairs:
            return []
        
        # Run scan if not done recently
        scan_results = self.scan_market()
        
        # Return top N buy signals
        buy_signals = [r for r in scan_results if r['signal'] == 1]
        return buy_signals[:n]
    
    def get_pair_info(self, symbol: str) -> Dict:
        """Get detailed info for a specific pair"""
        for pair in self.filtered_pairs:
            if pair['symbol'] == symbol:
                return pair
        return {}


class PortfolioManager:
    """Manages positions across multiple trading pairs"""
    
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.positions = {}  # symbol -> position info
        self.max_positions = int(getattr(config, 'max_positions', 5))
        self.position_size_pct = float(getattr(config, 'position_size_pct', 0.2))  # 20% per position
    
    def can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position"""
        if symbol in self.positions:
            return False  # Already have position
        
        if len(self.positions) >= self.max_positions:
            return False  # Max positions reached
        
        return True
    
    def add_position(self, symbol: str, entry_price: float, quantity: float, ml_score: float):
        """Add a new position"""
        self.positions[symbol] = {
            'symbol': symbol,
            'entry_price': entry_price,
            'quantity': quantity,
            'ml_score': ml_score,
            'entry_time': datetime.now().isoformat(),
            'status': 'OPEN'
        }
        self.logger.info(f"Position opened: {symbol} @ {entry_price} (qty: {quantity})")
    
    def close_position(self, symbol: str, exit_price: float):
        """Close a position"""
        if symbol not in self.positions:
            return
        
        position = self.positions[symbol]
        pnl = (exit_price - position['entry_price']) * position['quantity']
        pnl_pct = ((exit_price / position['entry_price']) - 1) * 100
        
        position['exit_price'] = exit_price
        position['exit_time'] = datetime.now().isoformat()
        position['pnl'] = pnl
        position['pnl_pct'] = pnl_pct
        position['status'] = 'CLOSED'
        
        self.logger.info(f"Position closed: {symbol} @ {exit_price} (P&L: ${pnl:.2f}, {pnl_pct:.2f}%)")
        
        # Remove from active positions
        del self.positions[symbol]
    
    def get_active_positions(self) -> List[Dict]:
        """Get all active positions"""
        return list(self.positions.values())
    
    def get_total_exposure(self) -> float:
        """Calculate total portfolio exposure"""
        return len(self.positions) * self.position_size_pct
    
    def update_position_prices(self, prices: Dict[str, float]):
        """Update current prices for all positions"""
        for symbol, position in self.positions.items():
            if symbol in prices:
                current_price = prices[symbol]
                unrealized_pnl = (current_price - position['entry_price']) * position['quantity']
                unrealized_pnl_pct = ((current_price / position['entry_price']) - 1) * 100
                
                position['current_price'] = current_price
                position['unrealized_pnl'] = unrealized_pnl
                position['unrealized_pnl_pct'] = unrealized_pnl_pct
