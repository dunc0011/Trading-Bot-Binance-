# Web UI Guide

## 🎨 Trading Bot Web Dashboard

A beautiful, modern web interface to control and monitor your trading bot in real-time!

## ✨ Features

- **🎮 Bot Control** - Start/stop the bot with a single click
- **📊 Real-time Monitoring** - Live status updates via WebSockets  
- **🎓 Model Training** - Train ML models directly from the UI
- **📈 Model Management** - View all trained models with metrics
- **📝 Live Logs** - Real-time log viewing with auto-refresh
- **⚙️ Configuration** - View current bot settings
- **🔔 Notifications** - Toast notifications for all actions
- **📱 Responsive** - Works on desktop and mobile

## 🚀 Quick Start

### Option 1: Using the Script (Recommended)

```bash
# Run the web UI
./run_web_ui.sh
```

### Option 2: Manual Start

```bash
# Install dependencies (if not already done)
pip install -r requirements.txt

# Run the web app
cd src
python web_app.py
```

### Option 3: Docker

```bash
# Add to docker-compose.yml (already configured)
docker-compose up web-ui
```

## 🌐 Accessing the Dashboard

Once started, open your browser and navigate to:

**http://localhost:5000**

You'll see a beautiful gradient purple background with a clean, modern interface!

## 📖 Dashboard Sections

### 1. Bot Controls

**Start/Stop Buttons**
- Click ▶️ **Start Bot** to begin trading
- Click ⏹️ **Stop Bot** to halt all trading
- 🔄 **Refresh** to update status

**Current Configuration**
- **Symbol**: Trading pair (e.g., ETHUSDT)
- **Timeframe**: Candle interval (e.g., 1h)
- **Strategy**: Active strategy (simple or ml_ema)
- **Dry Run**: Whether using simulation mode

### 2. ML Model Training

Train new models without leaving the browser!

**Training Form**:
- **Symbol**: Enter trading pair (ETHUSDT, BTCUSDT, etc.)
- **Interval**: Select timeframe (1m, 5m, 15m, 1h, 4h, 1d)
- **Lookback Days**: Number of days of historical data (1-365)

Click **🎓 Train Model** to start training in the background.

**Training Progress**:
- Spinner shows training is in progress
- Notification when complete
- Models list automatically refreshes

### 3. Trained Models

View all your trained ML models with detailed metrics:

- **Model Type**: RandomForest, GradientBoosting, or LogisticRegression
- **F1 Score**: Model performance metric
- **Accuracy**: Classification accuracy
- **Samples**: Number of training samples
- **Trained Date**: When the model was created

Click **🔄 Refresh Models** to update the list.

### 4. Recent Logs

Real-time log viewer with:
- Terminal-style display (green text on dark background)
- Last 100 log entries
- Auto-refresh every 10 seconds
- Manual refresh button
- Auto-scroll to latest entries

## 🎯 Usage Examples

### Example 1: Start Bot with ML Strategy

1. Make sure you have a trained model:
   ```bash
   # Train via UI or command line
   python -m src.utils.train_ml_model --symbol ETHUSDT --interval 1h
   ```

2. Update `.env`:
   ```bash
   STRATEGY=ml_ema
   DRY_RUN=true
   ```

3. Open dashboard: http://localhost:5000

4. Click **▶️ Start Bot**

5. Watch logs for activity!

### Example 2: Train a Model from UI

1. Open dashboard
2. Scroll to **ML Model Training** section
3. Enter:
   - Symbol: `BTCUSDT`
   - Interval: `4h`
   - Lookback Days: `120`
4. Click **🎓 Train Model**
5. Wait for completion notification
6. Check **Trained Models** section

### Example 3: Monitor Live Trading

1. Start bot (dry-run recommended)
2. Watch **Recent Logs** section
3. See real-time:
   - Market data fetching
   - Signal generation
   - Order execution (simulated in dry-run)
   - Model predictions

## 🎨 UI Design

**Color Scheme**:
- Primary: Blue (#2563eb)
- Success: Green (#10b981)
- Danger: Red (#ef4444)
- Background: Purple gradient

**Typography**:
- Modern system fonts
- Clean, readable layouts
- Responsive grid system

**Animations**:
- Smooth button hover effects
- Slide-in notifications
- Loading spinners

## 🔧 Configuration

### Environment Variables

```bash
# Flask configuration
FLASK_SECRET_KEY=your-secret-key-here

# Bot configuration (from .env)
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
STRATEGY=ml_ema
DRY_RUN=true
SYMBOL=ETHUSDT
TIMEFRAME=1h
```

### Port Configuration

Default port: **5000**

To change, edit `src/web_app.py`:
```python
run_web_app(host='0.0.0.0', port=8080, debug=True)
```

## 🐋 Docker Setup

The web UI is Docker-ready!

**docker-compose.yml** (add this service):
```yaml
services:
  web-ui:
    build: .
    container_name: trading-bot-web-ui
    ports:
      - "5000:5000"
    volumes:
      - ./logs:/app/logs
      - ./models:/app/models
      - ./src:/app/src
      - ./web:/app/web
    environment:
      - PYTHONUNBUFFERED=1
    command: python src/web_app.py
```

Run:
```bash
docker-compose up web-ui
```

## 🔒 Security Notes

### ⚠️ Important

- The UI runs on **localhost** by default (secure)
- **Never expose** to the internet without authentication
- Contains sensitive bot controls
- Can modify trading settings
- Logs may contain API activity

### Production Deployment

If you must expose externally:

1. Add authentication (Flask-Login)
2. Use HTTPS (reverse proxy with nginx)
3. Implement rate limiting
4. Use strong SECRET_KEY
5. Restrict IP access

**Example nginx config**:
```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🐛 Troubleshooting

### UI won't start

```bash
# Check dependencies
pip install -r requirements.txt

# Check port availability
lsof -i :5000

# Check logs
tail -f logs/trading_bot.log
```

### Bot won't start from UI

- Verify `.env` file exists
- Check API credentials
- Look at Recent Logs section
- Try starting from command line first

### Training fails

- Check Binance API limits
- Verify symbol exists (ETHUSDT, not ETH/USDT)
- Ensure enough historical data available
- Check logs for error messages

### Logs not showing

- Ensure `logs/` directory exists
- Check file permissions
- Verify logging is configured in bot

## 📱 Mobile Access

The UI is responsive and works on mobile!

**On same network**:
1. Find your computer's IP:
   ```bash
   ifconfig | grep "inet "
   ```
2. Access from phone: `http://YOUR_IP:5000`

**Note**: Ensure firewall allows port 5000

## 🎓 API Endpoints

For programmatic access:

```bash
# Get status
curl http://localhost:5000/api/status

# Start bot
curl -X POST http://localhost:5000/api/start

# Stop bot
curl -X POST http://localhost:5000/api/stop

# Get trained models
curl http://localhost:5000/api/models

# Get logs
curl http://localhost:5000/api/logs?lines=50

# Train model
curl -X POST http://localhost:5000/api/train \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT","interval":"1h","lookback_days":90}'
```

## 🔄 Real-time Updates

The dashboard uses **WebSockets** for real-time communication:

- Bot status changes
- Training completion
- Live log streaming (planned)
- Signal generation (planned)

## 🎬 Video Tour

1. Open dashboard
2. Train a model (takes 2-5 minutes)
3. Start bot in dry-run mode
4. Watch logs for activity
5. Stop bot when done

## 📚 Further Reading

- Main README: `README.md`
- Development Guide: `WARP.md`
- ML Strategy Details: `ML_INTEGRATION_SUMMARY.md`
- Git Guide: `GIT_DEPLOYMENT_GUIDE.md`

## 🆘 Support

If you encounter issues:
1. Check this guide's Troubleshooting section
2. Review logs in the UI
3. Check `logs/trading_bot.log` file
4. Verify `.env` configuration
5. Test bot from command line first

---

**Enjoy your new dashboard!** 🎉

Access it at: http://localhost:5000
