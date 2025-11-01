# Manual Position Sell Feature

## Overview
The web UI now includes a **Sell button** for each active position, allowing you to manually close positions at market price directly from the dashboard.

## Features

### UI Changes
- **Sell Button**: Each position in the Positions table now has a red "Sell" button in the Action column
- **Confirmation Dialog**: Clicking Sell prompts you to confirm the action with details about what will happen
- **Real-time Updates**: After selling, the positions table refreshes automatically to show the updated state
- **Visual Feedback**: Success/error notifications appear showing the execution price and P&L

### Backend Implementation

#### API Endpoint
- **Route**: `POST /api/sell_position`
- **Body**: `{"symbol": "BTCUSDT"}`
- **Response**: 
  ```json
  {
    "success": true,
    "message": "Position closed successfully",
    "symbol": "BTCUSDT",
    "price": 67432.50,
    "pnl": 15.23,
    "pnl_pct": 2.34
  }
  ```

#### What Happens When You Sell

1. **Validation**: Checks that the bot is running and the position exists
2. **Price Discovery**: Gets the current market price from Binance
3. **Order Execution**: 
   - In live mode: Places a real market SELL order on Binance
   - In dry-run mode: Simulates the sell
4. **Position Cleanup**:
   - Removes position from bot's `active_positions` dictionary
   - Unregisters from Real-time Position Monitor (RTM) trailing stops
   - Records the trade in performance tracker with reason "Manual close via UI"
5. **Notifications**:
   - Emits SocketIO event `trade_executed` with trade details
   - Logs the complete trade history

#### Safety Features

- **Confirmation Required**: User must confirm the sale in a dialog box
- **Proper Quantity Calculation**: Respects Binance LOT_SIZE filters and rounds correctly
- **Fee Awareness**: Uses fee-adjusted entry prices for accurate P&L calculation
- **Concurrent-Safe**: Thread-safe handling of position dictionary modifications
- **Error Handling**: Comprehensive error handling with detailed error messages
- **Logging**: Full audit trail in logs for debugging and compliance

## Usage

### From the Web UI (http://localhost:5000)

1. Navigate to the **Positions** tab
2. Find the position you want to close in the Active Positions table
3. Click the red **Sell** button in the Action column
4. Review the confirmation dialog:
   - Current market price
   - What will happen (market sell, close position, record trade)
5. Click **OK** to confirm or **Cancel** to abort
6. Watch for the success notification showing execution price and P&L
7. The position will disappear from the table after ~1 second

### When to Use Manual Sell

- **Take Profits Early**: Lock in gains before the trailing stop is hit
- **Cut Losses**: Exit a position that's moving against you
- **Risk Management**: Reduce exposure when market conditions change
- **Rebalancing**: Close positions to free up capital for better opportunities
- **Emergency Exit**: Quickly exit all positions if needed

## Technical Details

### Files Modified

1. **`web/static/js/dashboard.js`**
   - Added `sellPosition(symbol, currentPrice)` function
   - Updated positions table to include Action column with Sell button
   - Added confirmation dialog and notification handling

2. **`src/web_app.py`**
   - Added `/api/sell_position` endpoint (POST)
   - Implemented order execution logic with proper quantity calculation
   - Integrated with performance tracker and RTM cleanup
   - Added SocketIO event emission for real-time updates

### Integration Points

- **MultiPairBot**: Uses `bot_manager.bot.active_positions` dict
- **Binance API**: Uses `client.create_order()` for market sells
- **Performance Tracker**: Logs closed trades via `tracker.log_trade()`
- **RTM (Real-time Monitor)**: Calls `rtm.unregister_position()` to stop monitoring
- **SocketIO**: Emits `trade_executed` event for dashboard updates

## Limitations

- Only works when bot is running
- Only available for positions tracked in `active_positions`
- Market orders may have slippage (price moves between quote and fill)
- No partial closes - always sells the full position

## Future Enhancements

Potential improvements for future versions:

- [ ] Partial position close (sell 50%, 75%, etc.)
- [ ] Limit order option (close at specific price)
- [ ] Bulk close (close all positions at once)
- [ ] Close with take-profit offset (+1%, +2%, etc.)
- [ ] Scheduled closes (close at specific time)
- [ ] Conditional closes (close if price reaches X)

## Testing

### In Dry-Run Mode
- Sell button will simulate the order without executing on exchange
- Logs will show `[DRY RUN] Would execute SELL order`
- Position will still be removed from tracking
- Trade will be recorded with simulated price

### On Testnet
- Use Binance testnet to test with fake funds
- Set `TRADING_MODE=testnet` in `.env`
- Real orders are placed but with testnet money

### In Production
- Test with smallest position first
- Verify order appears in Binance order history
- Check that P&L matches expectations
- Ensure trade is recorded in performance tracker

## Support

If you encounter issues:

1. Check browser console for JavaScript errors
2. Check web app logs: `docker-compose logs -f web-ui`
3. Verify bot is running: Check Status indicator in UI
4. Check Binance API status if orders fail
5. Review trade history in performance tracker

## Changelog

### v1.0.0 (2025-10-31)
- Initial release of manual sell feature
- Added Sell button to positions table
- Implemented `/api/sell_position` endpoint
- Integrated with RTM and performance tracking
- Added confirmation dialog and notifications
