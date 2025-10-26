# Telegram Notifications Setup Guide

This guide will help you set up Telegram notifications for your trading bot.

## Step 1: Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Start a chat and send `/newbot`
3. Follow the prompts:
   - Give your bot a name (e.g., "My Trading Bot")
   - Give your bot a username (must end in `bot`, e.g., "mytrading_bot")
4. BotFather will give you a **Bot Token** - save this!
   - Example: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

## Step 2: Get Your Chat ID

### Option A: Using @userinfobot (Easiest)
1. Search for `@userinfobot` on Telegram
2. Start a chat with it
3. It will reply with your user ID - this is your **Chat ID**!

### Option B: Using Your Bot
1. Start a chat with your new bot (search for its username)
2. Send any message to it (e.g., "hello")
3. Visit this URL in your browser (replace `YOUR_BOT_TOKEN` with your actual token):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
4. Look for `"chat":{"id":123456789}` - that number is your **Chat ID**

## Step 3: Configure Your Bot

1. Copy `.env.example` to `.env` if you haven't already:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your Telegram credentials:
   ```bash
   TELEGRAM_NOTIFICATIONS=true
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID=987654321
   ```

## Step 4: Rebuild Docker (if using Docker)

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Step 5: Test It!

Start your bot and you should receive a "Bot Started" notification on Telegram!

```bash
docker-compose up
```

## What Notifications Will You Receive?

- 🤖 **Bot Status**: When bot starts/stops
- 🟢/🔴 **Trading Signals**: BUY/SELL signals with price and indicators
- ✅ **Order Execution**: Successful orders with details
- ❌ **Order Failures**: Failed orders with reason
- ⚠️ **Errors**: Critical errors during bot operation

## Notification Examples

### Bot Started
```
🤖 BOT STARTED
  • Symbol: BTCUSDT
  • Timeframe: 1h
  • Strategy: ml_ema
  • Mode: DRY RUN
  • Trading Mode: testnet
```

### Trading Signal
```
🟢 BUY SIGNAL
📊 Symbol: BTCUSDT
💰 Price: $42,350.00
📝 Reason: ML EMA crossover with 68% confidence

📈 Indicators:
  • EMA_5: 42,320.50
  • EMA_8: 42,310.25
  • RSI: 58.43
  • Confidence: 0.6834
```

### Order Executed
```
✅ ORDER EXECUTED
📊 Symbol: BTCUSDT
🔄 Action: BUY
🆔 Order ID: 12345678
💰 Price: 42,350.00
📦 Quantity: 0.0024
```

## Troubleshooting

### Not Receiving Messages?
1. Make sure `TELEGRAM_NOTIFICATIONS=true` in your `.env`
2. Verify your bot token and chat ID are correct
3. Check logs: `docker-compose logs -f` for any Telegram errors
4. Make sure you've sent at least one message to your bot

### Bot Says "Forbidden: bot was blocked by the user"?
1. Find your bot on Telegram
2. Click "Start" or send it a message
3. Restart your trading bot

### Wrong Chat?
- The bot sends messages to the `TELEGRAM_CHAT_ID` specified in `.env`
- To change where messages go, update that value
- You can also use a group chat ID (invite your bot to a group, then get the group's chat ID using the getUpdates method above)

## Group Notifications

Want notifications in a Telegram group?

1. Create a Telegram group
2. Add your bot to the group (as admin if needed)
3. Send a message in the group
4. Use the `getUpdates` URL method (Step 2, Option B) to find the group's chat ID
   - Group IDs are usually negative (e.g., `-123456789`)
5. Update `TELEGRAM_CHAT_ID` in `.env` with the group ID
6. Restart your bot

## Security Notes

- Keep your bot token secret! It's like a password.
- Don't commit your `.env` file to git (it's in `.gitignore` by default)
- Only share your bot username with people you trust
- Your bot can only send messages to chats where it's been added

## Disable Notifications

To temporarily disable notifications without removing your credentials:

```bash
TELEGRAM_NOTIFICATIONS=false
```

Then restart your bot.
