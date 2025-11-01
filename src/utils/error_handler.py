"""
Enhanced Error Handling and API Rate Limiting

Provides robust error handling for:
- API rate limits
- Network connectivity issues
- Invalid responses
- Authentication errors
- Circuit breaker pattern
"""
import logging
import asyncio
import time
from typing import Optional, Callable, Any
from binance.exceptions import BinanceAPIException, BinanceRequestException
import requests

logger = logging.getLogger(__name__)


class RateLimiter:
    """API rate limiter with exponential backoff"""

    def __init__(self, max_calls_per_minute: int = 1200):
        self.max_calls_per_minute = max_calls_per_minute
        self.calls = []
        self.backoff_time = 1.0

    async def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        current_time = time.time()

        # Remove calls older than 1 minute
        self.calls = [call for call in current_time - 60 if call > current_time - 60]

        if len(self.calls) >= self.max_calls_per_minute:
            # Calculate wait time
            oldest_call = min(self.calls)
            wait_time = 60 - (current_time - oldest_call)
            if wait_time > 0:
                logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        self.calls.append(current_time)

    def reset_backoff(self):
        """Reset backoff time after successful call"""
        self.backoff_time = 1.0

    async def exponential_backoff(self):
        """Apply exponential backoff"""
        logger.warning(f"Applying exponential backoff: {self.backoff_time}s")
        await asyncio.sleep(self.backoff_time)
        self.backoff_time = min(self.backoff_time * 2, 300)  # Max 5 minutes


class CircuitBreaker:
    """Circuit breaker pattern for API calls"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN

    def record_success(self):
        """Record successful call"""
        self.failure_count = 0
        self.state = 'CLOSED'

    def record_failure(self):
        """Record failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.error(f"Circuit breaker OPEN after {self.failure_count} failures")

    def can_attempt_call(self) -> bool:
        """Check if call can be attempted"""
        if self.state == 'CLOSED':
            return True

        if self.state == 'OPEN':
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = 'HALF_OPEN'
                logger.info("Circuit breaker HALF_OPEN - testing recovery")
                return True
            return False

        # HALF_OPEN state
        return True


class BinanceErrorHandler:
    """Enhanced error handler for Binance API calls"""

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.circuit_breaker = CircuitBreaker()
        self.max_retries = 3

    async def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic and error handling

        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result or None if all retries failed
        """
        for attempt in range(self.max_retries + 1):
            try:
                # Check circuit breaker
                if not self.circuit_breaker.can_attempt_call():
                    logger.error("Circuit breaker is OPEN, skipping call")
                    return None

                # Apply rate limiting
                await self.rate_limiter.wait_if_needed()

                # Execute function
                result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)

                # Record success
                self.circuit_breaker.record_success()
                self.rate_limiter.reset_backoff()

                return result

            except BinanceAPIException as e:
                await self._handle_binance_api_error(e, attempt)

            except BinanceRequestException as e:
                await self._handle_binance_request_error(e, attempt)

            except requests.exceptions.RequestException as e:
                await self._handle_request_error(e, attempt)

            except Exception as e:
                await self._handle_generic_error(e, attempt)

        logger.error(f"All {self.max_retries + 1} attempts failed")
        return None

    async def _handle_binance_api_error(self, e: BinanceAPIException, attempt: int):
        """Handle Binance API specific errors"""
        error_code = e.code
        error_msg = e.message

        logger.error(f"Binance API Error (attempt {attempt + 1}): Code {error_code} - {error_msg}")

        # Record failure for circuit breaker
        self.circuit_breaker.record_failure()

        # Handle specific error codes
        if error_code == -1003:  # Rate limit exceeded
            logger.warning("Rate limit exceeded, applying backoff")
            await self.rate_limiter.exponential_backoff()

        elif error_code == -1021:  # Timestamp error
            logger.warning("Timestamp error, retrying immediately")

        elif error_code == -1013:  # Invalid quantity
            logger.error("Invalid quantity/price - check order parameters")
            return  # Don't retry for parameter errors

        elif error_code == -2010:  # Account has insufficient balance
            logger.error("Insufficient balance for order")
            return  # Don't retry for balance issues

        else:
            # Apply backoff for unknown API errors
            await self.rate_limiter.exponential_backoff()

    async def _handle_binance_request_error(self, e: BinanceRequestException, attempt: int):
        """Handle Binance request errors"""
        logger.error(f"Binance Request Error (attempt {attempt + 1}): {e}")

        self.circuit_breaker.record_failure()
        await self.rate_limiter.exponential_backoff()

    async def _handle_request_error(self, e: requests.exceptions.RequestException, attempt: int):
        """Handle general request errors"""
        logger.error(f"Request Error (attempt {attempt + 1}): {e}")

        self.circuit_breaker.record_failure()
        await self.rate_limiter.exponential_backoff()

    async def _handle_generic_error(self, e: Exception, attempt: int):
        """Handle generic errors"""
        logger.error(f"Generic Error (attempt {attempt + 1}): {e}", exc_info=True)

        self.circuit_breaker.record_failure()
        await self.rate_limiter.exponential_backoff()


class TradingErrorHandler:
    """Error handler for trading operations"""

    def __init__(self):
        self.error_handler = BinanceErrorHandler()

    async def safe_get_klines(self, client, symbol: str, interval: str, limit: int = 100) -> Optional[list]:
        """Safely get klines with error handling"""
        async def _get_klines():
            return client.get_klines(symbol=symbol, interval=interval, limit=limit)

        result = await self.error_handler.execute_with_retry(_get_klines)
        return result

    async def safe_get_account(self, client) -> Optional[dict]:
        """Safely get account info with error handling"""
        async def _get_account():
            return client.get_account()

        result = await self.error_handler.execute_with_retry(_get_account)
        return result

    async def safe_place_order(self, client, **order_params) -> Optional[dict]:
        """Safely place order with error handling"""
        async def _place_order():
            return client.create_order(**order_params)

        result = await self.error_handler.execute_with_retry(_place_order)
        return result

    async def safe_cancel_order(self, client, symbol: str, order_id: str) -> Optional[dict]:
        """Safely cancel order with error handling"""
        async def _cancel_order():
            return client.cancel_order(symbol=symbol, orderId=order_id)

        result = await self.error_handler.execute_with_retry(_cancel_order)
        return result

    async def safe_get_open_orders(self, client, symbol: str) -> Optional[list]:
        """Safely get open orders with error handling"""
        async def _get_open_orders():
            return client.get_open_orders(symbol=symbol)

        result = await self.error_handler.execute_with_retry(_get_open_orders)
        return result


# Global error handler instance
trading_error_handler = TradingErrorHandler()