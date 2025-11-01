"""
Flask Web Application for Trading Bot Control and Monitoring
"""
import os
import json
import logging
import concurrent.futures
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
            
            # Start bot in separate thread with persistent event loop
            def run_bot():
                global bot_running
                bot_running = True
                import asyncio
                
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Run bot and keep loop alive
                    loop.run_until_complete(self.bot.start())
                except Exception as e:
                    logger.error(f"Bot crashed: {e}", exc_info=True)
                finally:
                    bot_running = False
                    loop.close()
                    logger.info("Bot event loop closed")
            
            self.thread = Thread(target=run_bot, daemon=True)
            self.thread.start()
            self.status = 'running'
            logger.info("Bot thread started")
            
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
        """Get active positions from multi-pair bot with trailing stop info"""
        if not self.bot or not hasattr(self.bot, 'active_positions'):
            return []
        
        positions = []
        # Copy dict to avoid "dictionary changed size during iteration" error
        active_positions_snapshot = dict(self.bot.active_positions)
        
        for symbol, pos in active_positions_snapshot.items():
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
                
                # Get RTM trailing stop info if available
                peak_price = pos.get('highest_price')  # Fallback to legacy field
                trailing_stop = None
                
                if hasattr(self.bot, 'rtm') and self.bot.rtm:
                    try:
                        import asyncio
                        # Get RTM's event loop - try self.bot.rtm.loop first, fallback to getting from bot thread
                        rtm_loop = self.bot.rtm.loop
                        
                        if not rtm_loop:
                            # RTM not started yet or loop not set
                            logger.debug(f"RTM loop not available yet for {symbol}")
                        else:
                            # Use bot's event loop to get RTM data
                            future = asyncio.run_coroutine_threadsafe(
                                self.bot.rtm.get_position_data(symbol),
                                rtm_loop
                            )
                            rtm_data = future.result(timeout=1.0)  # 1s timeout
                            
                            if rtm_data:
                                peak_price = rtm_data['peak_price']
                                trailing_stop = rtm_data['trailing_stop']
                                logger.info(f"✅ RTM data for {symbol}: peak=${peak_price:.2f}, stop=${trailing_stop:.2f}")
                            else:
                                logger.info(f"⚠️  RTM returned None for {symbol} (position not tracked yet)")
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"⏱️  Timeout getting RTM data for {symbol}")
                    except Exception as e:
                        logger.warning(f"❌ Could not get RTM info for {symbol}: {e}")
                
                # Ensure peak is never less than current (handle race condition)
                if peak_price and current_price > peak_price:
                    peak_price = current_price
                
                positions.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'size': size,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'ml_confidence': pos.get('ml_confidence', 0),
                    'duration': duration,
                    'peak_price': peak_price,
                    'trailing_stop': trailing_stop
                })
            except Exception as e:
                logger.error(f"Error getting position info for {symbol}: {e}", exc_info=True)
                # Still add position with basic info even if RTM fetch fails
                try:
                    positions.append({
                        'symbol': symbol,
                        'entry_price': pos['entry_price'],
                        'current_price': pos.get('entry_price', 0),  # Fallback to entry
                        'size': pos.get('size', 0),
                        'pnl': 0,
                        'pnl_pct': 0,
                        'ml_confidence': pos.get('ml_confidence', 0),
                        'duration': 'Error',
                        'peak_price': pos.get('entry_price', 0),
                        'trailing_stop': None
                    })
                except:
                    pass
        
        return positions


bot_manager = BotManager()


# Routes
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


@app.route('/rl')
def rl_training():
    """RL agent training page"""
    return render_template('rl_training.html')


@app.route('/learning')
def learning_analytics():
    """Learning analytics dashboard"""
    return render_template('learning_analytics.html')


@app.route('/api/learning/analytics')
def api_learning_analytics():
    """Get learning analytics data"""
    try:
        from utils.trade_logger import TradeLogger
        logger_instance = TradeLogger()
        
        # Get stats and win rates by context
        stats = logger_instance.get_stats()
        context_data = logger_instance.get_win_rate_by_context()
        
        return jsonify({
            'success': True,
            'stats': stats,
            'by_confidence': context_data.get('by_confidence', []),
            'by_regime': context_data.get('by_regime', []),
            'by_confluence': context_data.get('by_confluence', [])
        })
    except Exception as e:
        logger.error(f"Error fetching learning analytics: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})




@app.route('/tensorboard')
def tensorboard_viewer():
    """TensorBoard viewer for RL training visualization"""
    return render_template('tensorboard.html')


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


@app.route('/api/rl/train', methods=['POST'])
def api_rl_train():
    """Train RL agent for a specific symbol"""
    data = request.json
    symbol = data.get('symbol', 'BTCUSDT')
    timeframe = data.get('timeframe', '5m')
    lookback_days = data.get('lookback_days', 180)
    total_timesteps = data.get('total_timesteps', 100000)
    algorithm = data.get('algorithm', 'PPO')
    
    try:
        from utils.rl_agent import train_rl_agent_for_symbol
        
        # Start RL training in background thread
        def rl_train_worker():
            try:
                socketio.emit('rl_training_progress', {
                    'symbol': symbol,
                    'status': 'started',
                    'message': f'Starting {algorithm} training for {symbol}'
                })
                
                # Train agent
                agent, eval_stats = train_rl_agent_for_symbol(
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_days=lookback_days,
                    total_timesteps=total_timesteps
                )
                
                # Emit completion
                socketio.emit('rl_training_complete', {
                    'success': True,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'stats': eval_stats
                })
                
            except Exception as e:
                logger.error(f"RL training failed for {symbol}: {e}", exc_info=True)
                socketio.emit('rl_training_complete', {
                    'success': False,
                    'symbol': symbol,
                    'error': str(e)
                })
        
        thread = Thread(target=rl_train_worker, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'{algorithm} training started for {symbol} {timeframe}',
            'symbol': symbol,
            'timeframe': timeframe,
            'total_timesteps': total_timesteps
        })
    
    except Exception as e:
        logger.error(f"RL training failed: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/rl/models')
def api_rl_models():
    """List available trained RL models"""
    models_dir = Path('models/rl_agents')
    
    if not models_dir.exists():
        return jsonify({'success': True, 'models': []})
    
    models = []
    for meta_file in models_dir.glob('*.meta.json'):
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                models.append({
                    'file': meta_file.stem,
                    'symbol': meta.get('symbol'),
                    'timeframe': meta.get('timeframe'),
                    'algorithm': meta.get('algorithm'),
                    'trained_at': meta.get('trained_at'),
                    'total_timesteps': meta.get('total_timesteps'),
                    'data_samples': meta.get('data_samples'),
                    'evaluation': meta.get('evaluation', {})
                })
        except Exception as e:
            logger.error(f"Error reading {meta_file}: {e}")
    
    return jsonify({'success': True, 'models': models})


@app.route('/api/rl/auto_train', methods=['POST'])
def api_rl_auto_train():
    """Automatically train RL agents for top volume pairs"""
    data = request.json or {}
    max_pairs = data.get('max_pairs', 10)
    timeframe = data.get('timeframe', '5m')
    lookback_days = data.get('lookback_days', 180)
    total_timesteps = data.get('total_timesteps', 100000)
    
    try:
        from utils.rl_auto_trainer import RLAutoTrainer
        
        # Start auto-trainer in background thread
        def auto_train_worker():
            try:
                socketio.emit('rl_auto_training_started', {
                    'message': f'Discovering top {max_pairs} pairs and starting training...',
                    'max_pairs': max_pairs
                })
                
                trainer = RLAutoTrainer(
                    max_pairs=max_pairs,
                    timeframe=timeframe,
                    lookback_days=lookback_days,
                    total_timesteps=total_timesteps
                )
                
                # Run single training cycle (not continuous)
                trainer.train_all_pairs_once()
                
                socketio.emit('rl_auto_training_complete', {
                    'success': True,
                    'message': f'Successfully trained models for top {max_pairs} pairs'
                })
                
            except Exception as e:
                logger.error(f"RL auto-training failed: {e}", exc_info=True)
                socketio.emit('rl_auto_training_complete', {
                    'success': False,
                    'error': str(e)
                })
        
        thread = Thread(target=auto_train_worker, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Auto-training started for top {max_pairs} pairs'
        })
    
    except Exception as e:
        logger.error(f"Failed to start auto-training: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/rl/evaluate', methods=['POST'])
def api_rl_evaluate():
    """Evaluate a trained RL model"""
    data = request.json
    symbol = data.get('symbol', 'BTCUSDT')
    timeframe = data.get('timeframe', '5m')
    n_episodes = data.get('n_episodes', 10)
    
    try:
        from utils.rl_agent import RLTradingAgent
        from binance.client import Client
        from datetime import datetime, timedelta
        import pandas as pd
        
        # Load agent
        agent = RLTradingAgent(symbol=symbol, timeframe=timeframe)
        agent.load()
        
        # Fetch test data
        config = Config()
        if config.trading_mode == "testnet":
            client = Client(config.api_key, config.api_secret, testnet=True)
        else:
            client = Client(config.api_key, config.api_secret)
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=30)  # Test on last 30 days
        
        klines = client.get_historical_klines(
            symbol=symbol,
            interval=timeframe,
            start_str=str(int(start_time.timestamp() * 1000)),
            end_str=str(int(end_time.timestamp() * 1000))
        )
        
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'num_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Add features (same as training)
        df['returns'] = df['close'].pct_change()
        df['sma_10'] = df['close'].rolling(10).mean()
        df['sma_30'] = df['close'].rolling(30).mean()
        df['volume_sma'] = df['volume'].rolling(10).mean()
        df['volatility'] = df['returns'].rolling(20).std()
        
        # Drop NaN
        df = df.dropna()
        
        # Evaluate
        eval_stats = agent.evaluate(df, n_episodes=n_episodes)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'timeframe': timeframe,
            'stats': eval_stats
        })
    
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'message': f'No trained model found for {symbol} {timeframe}'
        })
    except Exception as e:
        logger.error(f"RL evaluation failed: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/learning/stats')
def api_learning_stats():
    """Get learning statistics from TradeLogger"""
    try:
        from utils.trade_logger import TradeLogger
        logger_obj = TradeLogger()
        
        # Use the built-in get_stats method
        stats = logger_obj.get_stats()
        context_stats = logger_obj.get_win_rate_by_context()
        
        return jsonify({
            'success': True,
            'stats': stats,
            'context_stats': context_stats
        })
    except Exception as e:
        logger.error(f"Error fetching learning stats: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/learning/trades')
def api_learning_trades():
    """Get recent trades with full details"""
    try:
        from utils.trade_logger import TradeLogger
        logger_obj = TradeLogger()
        
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 500)  # Cap at 500
        
        trades_df = logger_obj.get_recent_trades(limit=limit)
        
        if trades_df.empty:
            return jsonify({
                'success': True,
                'trades': [],
                'count': 0
            })
        
        # Convert DataFrame to list of dicts
        trades_json = trades_df.to_dict('records')
        
        return jsonify({
            'success': True,
            'trades': trades_json,
            'count': len(trades_json)
        })
    except Exception as e:
        logger.error(f"Error fetching trades: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/learning/performance')
def api_learning_performance():
    """Get performance metrics over time"""
    try:
        from utils.trade_logger import TradeLogger
        import pandas as pd
        logger_obj = TradeLogger()
        
        # Get trades grouped by day
        trades_df = logger_obj.get_recent_trades(limit=500)
        
        if trades_df.empty:
            return jsonify({
                'success': True,
                'performance': [],
                'cumulative_returns': []
            })
        
        # Convert entry_time to datetime and extract date
        trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
        trades_df['date'] = trades_df['entry_time'].dt.date.astype(str)
        
        # Group by date
        daily_stats = trades_df.groupby('date').agg({
            'profit_pct': ['count', 'sum', 'mean'],
            'outcome': lambda x: (x == 'WIN').sum(),
            'ml_confidence': 'mean'
        }).reset_index()
        
        # Flatten column names
        daily_stats.columns = ['date', 'trades', 'total_profit_pct', 'avg_profit_pct', 'wins', 'avg_confidence']
        daily_stats['win_rate'] = daily_stats['wins'] / daily_stats['trades']
        
        # Calculate cumulative returns
        daily_stats['cumulative_return'] = daily_stats['total_profit_pct'].cumsum()
        
        performance_data = daily_stats[['date', 'trades', 'wins', 'win_rate', 'total_profit_pct', 'avg_confidence']].to_dict('records')
        cumulative_returns = daily_stats[['date', 'cumulative_return']].to_dict('records')
        
        return jsonify({
            'success': True,
            'performance': performance_data,
            'cumulative_returns': cumulative_returns
        })
    except Exception as e:
        logger.error(f"Error fetching performance: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/logs')
def api_logs():
    """Get recent log entries from specific log file"""
    logs_dir = Path('logs')
    
    # Query params
    requested_file = request.args.get('file', 'multi_pair_bot.log')
    tail = request.args.get('tail', 500, type=int)
    tail = min(tail, 5000)  # Cap at 5000 lines
    
    # Whitelist allowed files
    allowed_files = [
        'multi_pair_bot.log',
        'trading_bot.log',
        'ml_training.log',
        'advanced_ml_training.log'
    ]
    
    if requested_file not in allowed_files:
        return jsonify({
            'success': False,
            'message': f'File not allowed. Choose from: {", ".join(allowed_files)}'
        })
    
    log_file = logs_dir / requested_file
    
    if not log_file.exists():
        # Try to find any log file as fallback
        for fallback in ['multi_pair_bot.log', 'trading_bot.log']:
            fallback_path = logs_dir / fallback
            if fallback_path.exists():
                log_file = fallback_path
                requested_file = fallback
                break
        else:
            return jsonify({
                'success': True,
                'file': requested_file,
                'lines': [],
                'message': f'Log file {requested_file} not found yet (bot may not have started)'
            })
    
    try:
        # Efficiently tail the file
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-tail:] if len(all_lines) > tail else all_lines
        
        file_size = log_file.stat().st_size
        
        return jsonify({
            'success': True,
            'file': requested_file,
            'lines': recent_lines,
            'size_bytes': file_size,
            'total_lines': len(all_lines),
            'returned_lines': len(recent_lines)
        })
    
    except Exception as e:
        logger.error(f"Error reading {log_file}: {e}", exc_info=True)
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


@app.route('/api/sell_position', methods=['POST'])
def api_sell_position():
    """Manually close a position at market price"""
    try:
        data = request.json
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({'success': False, 'message': 'Symbol is required'})
        
        # Check if bot is running and has the position
        if not bot_manager.bot or not hasattr(bot_manager.bot, 'active_positions'):
            return jsonify({'success': False, 'message': 'Bot not running or no positions available'})
        
        if symbol not in bot_manager.bot.active_positions:
            return jsonify({'success': False, 'message': f'Position {symbol} not found'})
        
        # Get position details
        position = bot_manager.bot.active_positions[symbol]
        entry_price = position['entry_price']
        size_usdt = position['size']
        
        # Get current price
        ticker = bot_manager.bot.client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])
        
        # Calculate P&L
        pnl = (current_price - entry_price) * (size_usdt / entry_price)
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        logger.info(f"Manual sell requested for {symbol}: entry=${entry_price:.2f}, current=${current_price:.2f}, P&L=${pnl:.2f}")
        
        # Execute market sell order
        if not bot_manager.config.dry_run:
            try:
                client = bot_manager.bot.client
                # Get symbol info for quantity precision and notional
                symbol_info = client.get_symbol_info(symbol)
                
                # Filters
                lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] in ('MIN_NOTIONAL','NOTIONAL','MARKET_MIN_NOTIONAL')), None)
                
                step_size = float(lot_size_filter['stepSize']) if lot_size_filter else 0.000001
                min_notional = float(min_notional_filter.get('minNotional', 0)) if min_notional_filter else 0
                
                # Determine base asset and fetch available balance
                if symbol.endswith('USDT'):
                    base_asset = symbol[:-4]
                else:
                    # Fallback: take until last 4 chars
                    base_asset = symbol.replace('USDT', '')
                
                balance = client.get_asset_balance(asset=base_asset)
                available_qty = float(balance.get('free', 0))
                
                if available_qty <= 0:
                    return jsonify({'success': False, 'message': f'No available balance for {base_asset} to sell'})
                
                # Safety margin to avoid insufficient balance due to fees/dust
                target_qty = available_qty * 0.999
                
                # Round down to step size
                from decimal import Decimal, ROUND_DOWN
                step_size_decimal = Decimal(str(step_size))
                qty_decimal = Decimal(str(target_qty))
                qty_rounded = float((qty_decimal / step_size_decimal).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size_decimal)
                
                # Ensure notional meets minimum
                notional = qty_rounded * current_price
                if min_notional and notional < min_notional:
                    return jsonify({'success': False, 'message': f'Order notional ${notional:.2f} below minimum ${min_notional:.2f}'})
                
                if qty_rounded <= 0:
                    return jsonify({'success': False, 'message': 'Calculated sell quantity is too small after rounding'})
                
                logger.info(f"Executing SELL order for {symbol}: qty={qty_rounded} (avail={available_qty}, price={current_price})")
                
                # Place market sell order
                order = client.create_order(
                    symbol=symbol,
                    side='SELL',
                    type='MARKET',
                    quantity=qty_rounded
                )
                
                logger.info(f"✅ Market sell executed: {order}")
                
                # Actual fill price and qty
                fills = order.get('fills', [])
                if fills:
                    # Weighted average fill
                    total_qty = sum(float(f.get('qty', 0) or f.get('quantity', 0) or 0) for f in fills) or qty_rounded
                    total_quote = sum(float(f.get('price', current_price)) * float(f.get('qty', 0) or f.get('quantity', 0) or 0) for f in fills)
                    fill_price = (total_quote / total_qty) if total_qty > 0 else current_price
                else:
                    fill_price = current_price
                
                # Use the actual qty sold for P&L computation
                quantity_sold = qty_rounded
            except Exception as e:
                logger.error(f"Failed to execute sell order for {symbol}: {e}", exc_info=True)
                return jsonify({'success': False, 'message': f'Order execution failed: {str(e)}'})
        else:
            logger.info(f"[DRY RUN] Would execute SELL order for {symbol}")
            fill_price = current_price
            # Assume we sell full virtual qty based on position size
            quantity_sold = size_usdt / entry_price if entry_price else 0.0
        
        # Record the trade in performance tracker
        try:
            from performance_tracker import PerformanceTracker
            tracker = PerformanceTracker()
            
            tracker.log_trade(
                symbol=symbol,
                action='SELL',
                entry_price=entry_price,
                exit_price=fill_price,
                size=size_usdt,
                pnl=pnl,
                pnl_pct=pnl_pct,
                ml_confidence=position.get('ml_confidence', 0),
                reason='Manual close via UI'
            )
            logger.info(f"Trade logged to performance tracker")
        except Exception as e:
            logger.warning(f"Failed to log trade to performance tracker: {e}")
        
        # Remove from active positions
        del bot_manager.bot.active_positions[symbol]
        logger.info(f"Position {symbol} removed from active_positions")
        
        # Remove from RTM tracking if exists
        if hasattr(bot_manager.bot, 'rtm') and bot_manager.bot.rtm:
            try:
                import asyncio
                rtm_loop = bot_manager.bot.rtm.loop
                if rtm_loop:
                    future = asyncio.run_coroutine_threadsafe(
                        bot_manager.bot.rtm.unregister_position(symbol),
                        rtm_loop
                    )
                    future.result(timeout=2.0)
                    logger.info(f"Position {symbol} removed from RTM tracker")
            except Exception as e:
                logger.warning(f"Failed to remove {symbol} from RTM: {e}")
        
        # Emit update via SocketIO
        socketio.emit('trade_executed', {
            'symbol': symbol,
            'action': 'SELL',
            'price': fill_price,
            'size': size_usdt,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'confidence': position.get('ml_confidence', 0),
            'timestamp': datetime.now().isoformat(),
            'manual': True
        })
        
        return jsonify({
            'success': True,
            'message': f'Position closed successfully',
            'symbol': symbol,
            'price': fill_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })
    
    except Exception as e:
        logger.error(f"Error selling position: {e}", exc_info=True)
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


@app.route('/api/train/advanced', methods=['POST'])
def api_train_advanced():
    """Train a single advanced ML model (called by UI)"""
    data = request.json
    symbol = data.get('symbol')
    interval = data.get('interval', '15m')
    lookback_days = data.get('lookback_days', 180)
    optimize = data.get('optimize', False)
    
    if not symbol:
        return jsonify({'success': False, 'message': 'Symbol is required'})
    
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from utils.train_advanced_model import main as train_advanced_main
        
        # Start training in background thread
        def train_worker():
            try:
                old_argv = sys.argv
                sys.argv = ['train_advanced_ml_model', '--symbol', symbol, 
                           '--interval', interval, '--lookback-days', str(lookback_days)]
                if optimize:
                    sys.argv.append('--optimize')
                
                train_advanced_main()
                sys.argv = old_argv
                
                # Emit success
                socketio.emit('batch_training_progress', {
                    'symbol': symbol,
                    'status': 'complete'
                })
            except Exception as e:
                logger.error(f"Training failed for {symbol}: {e}", exc_info=True)
                socketio.emit('batch_training_progress', {
                    'symbol': symbol,
                    'status': 'error',
                    'error': str(e)
                })
        
        thread = Thread(target=train_worker, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Training started for {symbol}'
        })
    
    except Exception as e:
        logger.error(f"Failed to start training: {e}", exc_info=True)
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


@app.route('/analytics')
def analytics():
    """Analytics page"""
    return render_template('analytics.html')


@app.route('/api/analytics/overview')
def api_analytics_overview():
    """Get overall performance stats"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total_trades,
                    ROUND(SUM(pnl), 2) as total_pnl,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
            ''')
            row = cursor.fetchone()
            stats = dict(row) if row else {'total_trades': 0, 'total_pnl': 0, 'avg_pnl': 0, 'win_rate': 0}
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"Error getting analytics overview: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/top-pairs')
def api_analytics_top_pairs():
    """Get top performing pairs"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    symbol,
                    COUNT(*) as trades,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY symbol
                HAVING COUNT(*) >= 3
                ORDER BY avg_pnl DESC
                LIMIT 5
            ''')
            pairs = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'success': True, 'pairs': pairs})
    except Exception as e:
        logger.error(f"Error getting top pairs: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/daily-pnl')
def api_analytics_daily_pnl():
    """Get daily P&L data"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    DATE(exit_time) as trade_date,
                    ROUND(SUM(pnl), 2) as daily_pnl
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY DATE(exit_time)
                ORDER BY trade_date
            ''')
            data = [dict(row) for row in cursor.fetchall()]
        
        dates = [row['trade_date'] for row in data]
        pnl = [row['daily_pnl'] for row in data]
        
        return jsonify({'success': True, 'dates': dates, 'pnl': pnl})
    except Exception as e:
        logger.error(f"Error getting daily P&L: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/confidence')
def api_analytics_confidence():
    """Get performance by confidence level"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    CASE 
                        WHEN ml_confidence < 0.60 THEN '50-60%'
                        WHEN ml_confidence < 0.70 THEN '60-70%'
                        WHEN ml_confidence < 0.80 THEN '70-80%'
                        WHEN ml_confidence < 0.90 THEN '80-90%'
                        ELSE '90-100%'
                    END as conf_range,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE ml_confidence IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY conf_range
                ORDER BY conf_range
            ''')
            data = [dict(row) for row in cursor.fetchall()]
        
        ranges = [row['conf_range'] for row in data]
        win_rates = [row['win_rate'] for row in data]
        
        return jsonify({'success': True, 'ranges': ranges, 'win_rates': win_rates})
    except Exception as e:
        logger.error(f"Error getting confidence data: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/by-symbol')
def api_analytics_by_symbol():
    """Get performance breakdown by symbol"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    symbol,
                    COUNT(*) as trades,
                    ROUND(SUM(pnl), 2) as total_pnl,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
                    ROUND(AVG(ml_confidence) * 100, 1) as avg_confidence
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY symbol
                HAVING COUNT(*) >= 1
                ORDER BY total_pnl DESC
            ''')
            symbols_data = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'success': True, 'symbols': symbols_data})
    except Exception as e:
        logger.error(f"Error getting by-symbol data: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/by-time')
def api_analytics_by_time():
    """Get performance breakdown by hour and day of week"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Hour of day analysis
            hour_cursor = conn.execute('''
                SELECT 
                    CAST(strftime('%H', exit_time) AS INTEGER) as hour,
                    COUNT(*) as trades,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY hour
                ORDER BY hour
            ''')
            hour_data = [dict(row) for row in hour_cursor.fetchall()]
            
            # Day of week analysis (0=Sunday, 6=Saturday)
            day_cursor = conn.execute('''
                SELECT 
                    CAST(strftime('%w', exit_time) AS INTEGER) as day,
                    COUNT(*) as trades,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                GROUP BY day
                ORDER BY day
            ''')
            day_data = [dict(row) for row in day_cursor.fetchall()]
        
        # Map day numbers to names
        day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        for item in day_data:
            item['day_name'] = day_names[item['day']]
        
        return jsonify({'success': True, 'by_hour': hour_data, 'by_day': day_data})
    except Exception as e:
        logger.error(f"Error getting by-time data: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/confidence-pnl')
def api_analytics_confidence_pnl():
    """Get average P&L by confidence level"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    CASE 
                        WHEN ml_confidence < 0.60 THEN '50-60%'
                        WHEN ml_confidence < 0.70 THEN '60-70%'
                        WHEN ml_confidence < 0.80 THEN '70-80%'
                        WHEN ml_confidence < 0.90 THEN '80-90%'
                        ELSE '90-100%'
                    END as conf_range,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                    COUNT(*) as trades
                FROM trades
                WHERE ml_confidence IS NOT NULL
                    AND exit_time >= datetime('now', '-30 days')
                GROUP BY conf_range
                ORDER BY conf_range
            ''')
            data = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting confidence P&L data: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/analytics/hold-duration')
def api_analytics_hold_duration():
    """Get performance by hold duration"""
    try:
        from performance_tracker import PerformanceTracker
        tracker = PerformanceTracker()
        
        import sqlite3
        with sqlite3.connect(tracker.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT 
                    CASE 
                        WHEN (julianday(exit_time) - julianday(entry_time)) * 24 < 1 THEN '< 1h'
                        WHEN (julianday(exit_time) - julianday(entry_time)) * 24 < 4 THEN '1-4h'
                        WHEN (julianday(exit_time) - julianday(entry_time)) * 24 < 12 THEN '4-12h'
                        WHEN (julianday(exit_time) - julianday(entry_time)) * 24 < 24 THEN '12-24h'
                        ELSE '> 24h'
                    END as duration_range,
                    COUNT(*) as trades,
                    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
                FROM trades
                WHERE exit_time >= datetime('now', '-30 days')
                    AND entry_time IS NOT NULL
                GROUP BY duration_range
                ORDER BY 
                    CASE duration_range
                        WHEN '< 1h' THEN 1
                        WHEN '1-4h' THEN 2
                        WHEN '4-12h' THEN 3
                        WHEN '12-24h' THEN 4
                        WHEN '> 24h' THEN 5
                    END
            ''')
            data = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting hold duration data: {e}")
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
        
        # Load available models (check both advanced and legacy)
        available_models = {}
        
        # Check advanced models first (preferred)
        advanced_dir = Path('models/advanced_ml')
        if advanced_dir.exists():
            for meta_file in advanced_dir.glob('*_advanced_ml.meta.json'):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    # Parse filename: BTCUSDT_5m_advanced_ml.meta.json
                    parts = meta_file.stem.replace('_advanced_ml.meta', '').split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        timeframe = parts[1]
                        key = f"{symbol}_{timeframe}"
                        
                        available_models[key] = {
                            'model_path': str(meta_file.with_suffix('.joblib')),
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'accuracy': meta.get('accuracy', 0),
                            'f1_score': meta.get('f1', 0),
                            'model_type': 'advanced'
                        }
                except Exception as e:
                    logger.debug(f"Error loading advanced model {meta_file}: {e}")
        
        # Fallback to legacy models (only if symbol not in advanced)
        legacy_dir = Path('models/ml_ema')
        if legacy_dir.exists():
            for model_file in legacy_dir.glob('*_ml_ema.joblib'):
                # Parse filename: BTCUSDT_1h_ml_ema.joblib
                parts = model_file.stem.split('_')
                if len(parts) >= 3:
                    symbol = parts[0]
                    timeframe = parts[1]
                    key = f"{symbol}_{timeframe}"
                    
                    # Skip if advanced model already loaded
                    if key in available_models:
                        continue
                    
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
                                'f1_score': meta.get('f1', 0),
                                'model_type': 'legacy'
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
                model_key = f"{symbol}_{config.timeframe}"  # Use configured timeframe
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
        
        # Return all pairs (was limited to 50)
        top_pairs = results
        
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


# Background task for live position updates
def emit_live_positions():
    """Emit position updates every 2 seconds"""
    import time
    while True:
        try:
            if bot_running and bot_manager.bot:
                positions = bot_manager.get_positions()
                socketio.emit('positions_update', {
                    'positions': positions,
                    'timestamp': datetime.now().isoformat()
                })
            time.sleep(2)  # Update every 2 seconds
        except Exception as e:
            logger.debug(f"Error emitting positions: {e}")
            time.sleep(2)

# Start background task
import threading
positions_thread = threading.Thread(target=emit_live_positions, daemon=True)
positions_thread.start()

# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('status', bot_manager.get_status())
    # Send initial positions
    if bot_running and bot_manager.bot:
        positions = bot_manager.get_positions()
        emit('positions_update', {
            'positions': positions,
            'timestamp': datetime.now().isoformat()
        })


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
