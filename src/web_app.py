"""
Flask Web Application for Trading Bot Control and Monitoring
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Thread

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from config.config import Config
from src.bot import TradingBot
from src.multi_pair_bot import MultiPairBot


# Initialize Flask app
app = Flask(__name__, 
            template_folder='../web/templates',
            static_folder='../web/static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
CORS(app)

# Initialize SocketIO for real-time updates
socketio = SocketIO(app, cors_allowed_origins="*")

# Global bot instance
bot_instance = None
bot_thread = None
bot_running = False

# Logger
logger = logging.getLogger(__name__)


class BotManager:
    """Manages bot lifecycle and state"""
    
    def __init__(self):
        self.bot = None
        self.config = None
        self.status = 'stopped'
        self.thread = None
        self.use_multi_pair = True  # Use multi-pair bot by default
    
    def start_bot(self):
        """Start the trading bot"""
        global bot_instance, bot_running
        
        if bot_running:
            return {'success': False, 'message': 'Bot already running'}
        
        try:
            self.config = Config()
            
            # Use multi-pair bot or single-pair bot
            if self.use_multi_pair:
                self.bot = MultiPairBot(self.config, socketio=socketio)
                logger.info("Starting Multi-Pair Bot with live updates")
            else:
                self.bot = TradingBot(self.config)
                logger.info("Starting Single-Pair Bot")
            
            bot_instance = self.bot
            
            # Start bot in separate thread
            def run_bot():
                global bot_running
                bot_running = True
                import asyncio
                asyncio.run(self.bot.start())
                bot_running = False
            
            self.thread = Thread(target=run_bot, daemon=True)
            self.thread.start()
            self.status = 'running'
            
            # Emit status update
            socketio.emit('bot_status', {'status': 'running'})
            
            bot_type = 'Multi-Pair' if self.use_multi_pair else 'Single-Pair'
            return {'success': True, 'message': f'{bot_type} Bot started successfully'}
        
        except Exception as e:
            logger.error(f"Failed to start bot: {e}", exc_info=True)
            return {'success': False, 'message': str(e)}
    
    def stop_bot(self, close_positions=False):
        """Stop the trading bot
        
        Args:
            close_positions: If True, close all open positions before stopping
        """
        global bot_running
        
        if not bot_running or not self.bot:
            return {'success': False, 'message': 'Bot not running'}
        
        try:
            # Optionally close all positions
            if close_positions and hasattr(self.bot, 'active_positions'):
                logger.info("Closing all open positions...")
                # TODO: Implement position closing logic
                # For now, just log - positions will remain open
                logger.warning("Position closing not yet implemented - positions will remain open")
            
            self.bot.stop()
            bot_running = False
            self.status = 'stopped'
            
            # Emit status update
            socketio.emit('bot_status', {'status': 'stopped'})
            
            return {'success': True, 'message': 'Bot stopped successfully (positions left open)'}
        
        except Exception as e:
            logger.error(f"Failed to stop bot: {e}", exc_info=True)
            return {'success': False, 'message': str(e)}
    
    def get_status(self):
        """Get current bot status"""
        bot_type = 'multi-pair' if self.use_multi_pair else 'single-pair'
        return {
            'running': bot_running,
            'status': self.status,
            'bot_type': bot_type,
            'config': {
                'symbol': self.config.symbol if self.config else None,
                'timeframe': self.config.timeframe if self.config else None,
                'strategy': self.config.strategy if self.config else None,
                'dry_run': self.config.dry_run if self.config else None,
            } if self.config else None
        }
    
    def get_positions(self):
        """Get active positions from multi-pair bot"""
        if not self.bot or not hasattr(self.bot, 'active_positions'):
            return []
        
        positions = []
        for symbol, pos in self.bot.active_positions.items():
            try:
                # Get current price
                ticker = self.bot.client.get_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
                
                # Calculate P&L
                entry_price = pos['entry_price']
                size = pos['size']
                pnl = (current_price - entry_price) * (size / entry_price)
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Calculate duration
                entry_time = datetime.fromisoformat(pos['timestamp'])
                duration = str(datetime.now() - entry_time).split('.')[0]
                
                positions.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'size': size,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'ml_confidence': pos.get('ml_confidence', 0),
                    'duration': duration
                })
            except Exception as e:
                logger.error(f"Error getting position info for {symbol}: {e}")
        
        return positions


bot_manager = BotManager()


# Routes
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    """Get bot status"""
    return jsonify(bot_manager.get_status())


@app.route('/api/portfolio')
def api_portfolio():
    """Get real-time portfolio overview"""
    try:
        # Get account info from Binance
        if bot_manager.bot and hasattr(bot_manager.bot, 'client'):
            account = bot_manager.bot.client.get_account()
            
            # Get USDT balance
            usdt_asset = [b for b in account['balances'] if b['asset'] == 'USDT'][0]
            usdt_free = float(usdt_asset['free'])
            usdt_locked = float(usdt_asset.get('locked', 0))
            usdt_total = usdt_free + usdt_locked
            
            # Get positions
            positions = bot_manager.get_positions()
            
            # Calculate total P&L
            total_pnl = sum(p['pnl'] for p in positions)
            total_pnl_pct = sum(p['pnl_pct'] for p in positions) / len(positions) if positions else 0
            
            # Get performance from tracker
            try:
                from performance_tracker import PerformanceTracker
                tracker = PerformanceTracker()
                trades = tracker.get_trades(limit=100)
                
                if trades:
                    winning_trades = len([t for t in trades if t['pnl'] > 0])
                    win_rate = (winning_trades / len(trades)) * 100
                    avg_pnl = sum(t['pnl_pct'] for t in trades) / len(trades)
                else:
                    win_rate = 0
                    avg_pnl = 0
            except:
                win_rate = 0
                avg_pnl = 0
            
            return jsonify({
                'success': True,
                'balance': {
                    'total': usdt_total,
                    'free': usdt_free,
                    'locked': usdt_locked,
                    'pnl_24h': total_pnl
                },
                'positions': {
                    'count': len(positions),
                    'total_exposure': sum(p['size'] for p in positions),
                    'total_pnl': total_pnl,
                    'avg_pnl_pct': total_pnl_pct
                },
                'performance': {
                    'total_trades': len(trades) if 'trades' in locals() else 0,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Bot not started'})
    
    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/start', methods=['POST'])
def api_start():
    """Start the trading bot"""
    result = bot_manager.start_bot()
    return jsonify(result)


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the trading bot"""
    result = bot_manager.stop_bot()
    return jsonify(result)


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Get or update bot configuration"""
    env_path = Path('.env')
    
    if request.method == 'GET':
        # Read current config
        config = {}
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        
        return jsonify({'success': True, 'config': config})
    
    elif request.method == 'POST':
        # Update config
        new_config = request.json
        
        try:
            # Read existing config
            lines = []
            if env_path.exists():
                with open(env_path, 'r') as f:
                    lines = f.readlines()
            
            # Update values
            updated_keys = set()
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    if key in new_config:
                        lines[i] = f"{key}={new_config[key]}\n"
                        updated_keys.add(key)
            
            # Add new keys
            for key, value in new_config.items():
                if key not in updated_keys:
                    lines.append(f"{key}={value}\n")
            
            # Write back
            with open(env_path, 'w') as f:
                f.writelines(lines)
            
            return jsonify({'success': True, 'message': 'Configuration updated'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})


@app.route('/api/train', methods=['POST'])
def api_train():
    """Trigger ML model training"""
    data = request.json
    symbol = data.get('symbol', 'ETHUSDT')
    interval = data.get('interval', '1h')
    lookback_days = data.get('lookback_days', 90)
    
    try:
        # Import training module
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from utils.train_ml_model import main as train_main
        
        # Start training in background thread
        def train_worker():
            import sys
            old_argv = sys.argv
            sys.argv = ['train_ml_model', '--symbol', symbol, '--interval', interval, 
                       '--lookback-days', str(lookback_days)]
            try:
                train_main()
                socketio.emit('training_complete', {'success': True, 'symbol': symbol})
            except Exception as e:
                socketio.emit('training_complete', {'success': False, 'error': str(e)})
            finally:
                sys.argv = old_argv
        
        thread = Thread(target=train_worker, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True, 
            'message': f'Training started for {symbol} {interval}',
            'symbol': symbol,
            'interval': interval,
            'lookback_days': lookback_days
        })
    
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/batch-train', methods=['POST'])
def api_batch_train():
    """Trigger batch ML model training for multiple pairs"""
    data = request.json
    symbols = data.get('symbols', ['ETHUSDT', 'BTCUSDT'])
    interval = data.get('interval', '1h')
    lookback_days = data.get('lookback_days', 90)
    optimize = data.get('optimize', False)
    
    # Handle 'ALL' symbol - auto-discover from Binance
    if symbols and symbols[0] == 'ALL':
        try:
            from binance.client import Client
            config = Config()
            
            if config.trading_mode == "testnet":
                client = Client(config.api_key, config.api_secret, testnet=True)
            else:
                client = Client(config.api_key, config.api_secret)
            
            # Get all USDT pairs with >$1M volume
            tickers = client.get_ticker()
            skip_tokens = ['USDC', 'BUSD', 'TUSD', 'DAI', 'USDP', 'FDUSD', 'UP', 'DOWN', 'BULL', 'BEAR']
            min_volume = 1_000_000
            
            discovered_pairs = []
            for ticker in tickers:
                symbol = ticker['symbol']
                if symbol.endswith('USDT') and not any(t in symbol for t in skip_tokens):
                    try:
                        volume = float(ticker['quoteVolume'])
                        if volume >= min_volume:
                            discovered_pairs.append((symbol, volume))
                    except (ValueError, KeyError):
                        continue
            
            # Sort by volume
            discovered_pairs.sort(key=lambda x: x[1], reverse=True)
            symbols = [s[0] for s in discovered_pairs]
            
            logger.info(f"Auto-discovered {len(symbols)} USDT pairs with >$1M volume")
            logger.info(f"Top 10: {', '.join(symbols[:10])}")
        except Exception as e:
            logger.error(f"Failed to auto-discover pairs: {e}")
            return jsonify({'success': False, 'message': f'Auto-discovery failed: {str(e)}'})
    
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from utils.train_advanced_model import main as train_advanced_main
        
        # Start batch training in background thread
        def batch_train_worker():
            results = []
            total = len(symbols)
            
            for idx, symbol in enumerate(symbols, 1):
                try:
                    # Emit progress
                    socketio.emit('batch_training_progress', {
                        'symbol': symbol,
                        'status': 'training',
                        'progress': idx,
                        'total': total
                    })
                    
                    # Train model
                    old_argv = sys.argv
                    sys.argv = ['train_advanced_ml_model', '--symbol', symbol, 
                               '--interval', interval, '--lookback-days', str(lookback_days)]
                    if optimize:
                        sys.argv.append('--optimize')
                    
                    train_advanced_main()
                    sys.argv = old_argv
                    
                    # Read model metadata
                    meta_path = Path(f'models/ml_ema/{symbol}_{interval}_ml_ema.meta.json')
                    if meta_path.exists():
                        with open(meta_path, 'r') as f:
                            meta = json.load(f)
                            results.append({
                                'symbol': symbol,
                                'success': True,
                                'f1_score': meta.get('f1'),
                                'accuracy': meta.get('accuracy'),
                                'model_type': meta.get('model')
                            })
                    else:
                        results.append({'symbol': symbol, 'success': True})
                    
                    # Emit success for this pair
                    socketio.emit('batch_training_progress', {
                        'symbol': symbol,
                        'status': 'complete',
                        'progress': idx,
                        'total': total
                    })
                    
                except Exception as e:
                    logger.error(f"Training failed for {symbol}: {e}", exc_info=True)
                    results.append({
                        'symbol': symbol,
                        'success': False,
                        'error': str(e)
                    })
                    
                    # Emit error for this pair
                    socketio.emit('batch_training_progress', {
                        'symbol': symbol,
                        'status': 'error',
                        'error': str(e),
                        'progress': idx,
                        'total': total
                    })
            
            # Emit final completion
            socketio.emit('batch_training_complete', {
                'success': True,
                'results': results,
                'total': total
            })
        
        thread = Thread(target=batch_train_worker, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Batch training started for {len(symbols)} pairs',
            'symbols': symbols,
            'interval': interval,
            'lookback_days': lookback_days,
            'optimize': optimize
        })
    
    except Exception as e:
        logger.error(f"Batch training failed: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/models')
def api_models():
    """List available trained models"""
    models_dir = Path('models/ml_ema')
    advanced_dir = Path('models/advanced_ml')
    
    models = []
    
    # Check advanced models first
    if advanced_dir.exists():
        for meta_file in advanced_dir.glob('*.meta.json'):
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                    models.append({
                        'file': meta_file.stem,
                        'symbol': meta.get('symbol'),
                        'interval': meta.get('interval'),
                        'model_type': meta.get('model_name', 'advanced'),
                        'f1_score': meta.get('f1'),
                        'accuracy': meta.get('accuracy'),
                        'trained_at': datetime.fromtimestamp(meta.get('trained_at', 0)).isoformat(),
                        'samples': meta.get('samples'),
                        'n_features': meta.get('n_features', 0)
                    })
            except Exception as e:
                logger.error(f"Error reading {meta_file}: {e}")
    
    # Check legacy models
    if models_dir.exists():
        for meta_file in models_dir.glob('*.meta.json'):
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                    models.append({
                        'file': meta_file.stem,
                        'symbol': meta.get('symbol'),
                        'interval': meta.get('interval'),
                        'model_type': meta.get('model', 'legacy'),
                        'f1_score': meta.get('f1'),
                        'accuracy': meta.get('accuracy'),
                        'trained_at': datetime.fromtimestamp(meta.get('trained_at', 0)).isoformat(),
                        'samples': meta.get('samples'),
                        'n_features': 0
                    })
            except Exception as e:
                logger.error(f"Error reading {meta_file}: {e}")
    
    return jsonify({'success': True, 'models': models})


@app.route('/api/logs')
def api_logs():
    """Get recent log entries from all log files"""
    logs_dir = Path('logs')
    lines = request.args.get('lines', 100, type=int)
    
    if not logs_dir.exists():
        return jsonify({'success': True, 'logs': []})
    
    try:
        all_logs = []
        
        # Get all log files
        log_files = sorted(logs_dir.glob('*.log'), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not log_files:
            return jsonify({'success': True, 'logs': ['No log files found']})
        
        # Read most recent log file first
        for log_file in log_files[:3]:  # Show up to 3 most recent log files
            try:
                with open(log_file, 'r') as f:
                    file_lines = f.readlines()
                    if file_lines:
                        all_logs.append(f"\n=== {log_file.name} (last {len(file_lines[-lines:])} lines) ===\n")
                        all_logs.extend(file_lines[-lines:])
            except Exception as e:
                logger.error(f"Error reading {log_file}: {e}")
        
        return jsonify({'success': True, 'logs': all_logs if all_logs else ['No logs available']})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/positions')
def api_positions():
    """Get current active positions"""
    try:
        positions = bot_manager.get_positions()
        
        # Calculate totals
        total_exposure = sum(p['size'] for p in positions)
        total_pnl = sum(p['pnl'] for p in positions)
        total_pnl_pct = (total_pnl / total_exposure * 100) if total_exposure > 0 else 0
        
        return jsonify({
            'success': True,
            'positions': positions,
            'total_exposure': total_exposure,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'bot_status': 'running' if bot_running else 'stopped'
        })
    except Exception as e:
        logger.error(f"Error getting positions: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/trades')
def api_trades():
    """Get recent trade history"""
    try:
        from performance_tracker import PerformanceTracker
        
        limit = request.args.get('limit', 20, type=int)
        tracker = PerformanceTracker()
        trades = tracker.get_trades(limit)
        
        return jsonify({
            'success': True,
            'trades': trades
        })
    except Exception as e:
        logger.error(f"Error getting trades: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/performance')
def api_performance():
    """Get performance chart data"""
    try:
        from performance_tracker import PerformanceTracker
        
        hours = request.args.get('hours', 24, type=int)
        tracker = PerformanceTracker()
        data = tracker.get_performance_chart_data(hours)
        
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        logger.error(f"Error getting performance data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/continuous-trainer/status')
def api_continuous_trainer_status():
    """Get continuous trainer status"""
    try:
        if bot_manager.bot and hasattr(bot_manager.bot, 'continuous_trainer'):
            status = bot_manager.bot.continuous_trainer.get_status()
            return jsonify({'success': True, 'status': status})
        else:
            return jsonify({
                'success': True,
                'status': {
                    'running': False,
                    'message': 'Continuous trainer not available (bot not started)'
                }
            })
    except Exception as e:
        logger.error(f"Error getting continuous trainer status: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/scan')
def api_scan_market():
    """Scan market for all USDT pairs with ML predictions"""
    try:
        from binance.client import Client
        import joblib
        import pandas as pd
        import numpy as np
        
        # Initialize Binance client
        config = Config()
        client = Client(
            config.api_key,
            config.api_secret,
            testnet=(config.trading_mode == 'testnet')
        )
        
        # Get 24h ticker data for all symbols
        logger.info("Fetching market data...")
        tickers = client.get_ticker()
        
        # Load available models
        models_dir = Path('models/ml_ema')
        available_models = {}
        if models_dir.exists():
            for model_file in models_dir.glob('*_ml_ema.joblib'):
                # Parse filename: BTCUSDT_1h_ml_ema.joblib
                parts = model_file.stem.split('_')
                if len(parts) >= 3:
                    symbol = parts[0]
                    timeframe = parts[1]
                    key = f"{symbol}_{timeframe}"
                    
                    # Load model metadata
                    meta_file = model_file.with_suffix('.meta.json')
                    if meta_file.exists():
                        with open(meta_file, 'r') as f:
                            meta = json.load(f)
                            available_models[key] = {
                                'model_path': str(model_file),
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'accuracy': meta.get('accuracy', 0),
                                'f1_score': meta.get('f1', 0)
                            }
        
        # Filter and process USDT pairs
        results = []
        skip_coins = ['USDC', 'BUSD', 'TUSD', 'DAI', 'UP', 'DOWN', 'BULL', 'BEAR']
        
        for ticker in tickers:
            symbol = ticker['symbol']
            
            # Only USDT pairs
            if not symbol.endswith('USDT'):
                continue
            
            # Skip stablecoins and leveraged tokens
            if any(coin in symbol for coin in skip_coins):
                continue
            
            try:
                volume = float(ticker['quoteVolume'])
                price = float(ticker['lastPrice'])
                price_change = float(ticker['priceChangePercent'])
                
                # Skip low-volume pairs
                if volume < 1_000_000:  # Min 1M USDT volume
                    continue
                
                # Check if we have a trained model
                model_key = f"{symbol}_1h"  # Default to 1h timeframe
                has_model = model_key in available_models
                ml_confidence = 0
                ml_signal = 'HOLD'
                model_accuracy = 0
                
                if has_model:
                    model_info = available_models[model_key]
                    model_accuracy = model_info['accuracy']
                    
                    # Get real ML prediction (slower but accurate)
                    try:
                        from strategies.ml_ema_strategy import MLEMAStrategy
                        
                        # Create temp config for this symbol
                        temp_config = Config()
                        temp_config.symbol = symbol
                        temp_config.timeframe = model_info['timeframe']
                        
                        # Initialize ML strategy
                        strategy = MLEMAStrategy(temp_config)
                        
                        # Get recent klines
                        klines = client.get_klines(
                            symbol=symbol,
                            interval=model_info['timeframe'],
                            limit=100
                        )
                        
                        # Get real ML prediction
                        signal = strategy.analyze(klines)
                        
                        if signal:
                            ml_signal = signal['action']
                            # Extract confidence from indicators if available
                            ml_confidence = signal.get('indicators', {}).get('confidence', 0) * 100
                            if ml_confidence == 0:
                                ml_confidence = 60 if ml_signal == 'BUY' else 50
                        else:
                            ml_signal = 'HOLD'
                            ml_confidence = 50
                            
                    except Exception as e:
                        logger.debug(f"Could not predict for {symbol}: {e}")
                        ml_signal = 'HOLD'
                        ml_confidence = 50
                
                results.append({
                    'symbol': symbol,
                    'price': price,
                    'volume_24h': volume,
                    'price_change_24h': price_change,
                    'has_model': has_model,
                    'ml_signal': ml_signal,
                    'ml_confidence': ml_confidence,
                    'model_accuracy': model_accuracy * 100 if model_accuracy else 0
                })
            
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping {symbol}: {e}")
                continue
        
        # Sort by volume (highest first)
        results.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        # Return top 50 pairs
        top_pairs = results[:50]
        
        return jsonify({
            'success': True,
            'pairs': top_pairs,
            'total_scanned': len(results),
            'models_available': len(available_models),
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Market scan failed: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('status', bot_manager.get_status())


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


@socketio.on('request_status')
def handle_status_request():
    """Handle status request from client"""
    emit('status', bot_manager.get_status())


def run_web_app(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask web application"""
    logger.info(f"Starting web interface on http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    run_web_app(debug=True)
