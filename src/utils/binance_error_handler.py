"""
Binance API Error Handler
Handles specific Binance API error codes and rate limiting
"""
import logging
import time
from functools import wraps

from binance.exceptions import BinanceAPIException


# Binance API Error Codes (from official documentation)
ERROR_CODES = {
    -1000: "UNKNOWN - An unknown error occurred while processing the request",
    -1001: "DISCONNECTED - Internal error; unable to process your request",
    -1002: "UNAUTHORIZED - You are not authorized to execute this request",
    -1003: "TOO_MANY_REQUESTS - Too many requests queued",
    -1006: "UNEXPECTED_RESP - An unexpected response was received",
    -1007: "TIMEOUT - Timeout waiting for response",
    -1014: "UNKNOWN_ORDER_COMPOSITION - Unsupported order combination",
    -1015: "TOO_MANY_ORDERS - Too many new orders",
    -1016: "SERVICE_SHUTTING_DOWN - This service is no longer available",
    -1020: "UNSUPPORTED_OPERATION - This operation is not supported",
    -1021: "INVALID_TIMESTAMP - Timestamp for this request is outside of the recvWindow",
    -1022: "INVALID_SIGNATURE - Signature for this request is not valid",
    -1099: "NOT_FOUND - Not found, authenticated, or authorized",
    -1100: "ILLEGAL_CHARS - Illegal characters found in a parameter",
    -1101: "TOO_MANY_PARAMETERS - Too many parameters sent for this endpoint",
    -1102: "MANDATORY_PARAM_EMPTY_OR_MALFORMED - A mandatory parameter was not sent",
    -1103: "UNKNOWN_PARAM - An unknown parameter was sent",
    -1104: "UNREAD_PARAMETERS - Not all sent parameters were read",
    -1105: "PARAM_EMPTY - A parameter was empty",
    -1106: "PARAM_NOT_REQUIRED - A parameter was sent when not required",
    -1111: "BAD_PRECISION - Precision is over the maximum defined",
    -1112: "NO_DEPTH - No orders on book for symbol",
    -1114: "TIF_NOT_REQUIRED - TimeInForce parameter sent when not required",
    -1115: "INVALID_TIF - Invalid timeInForce",
    -1116: "INVALID_ORDER_TYPE - Invalid orderType",
    -1117: "INVALID_SIDE - Invalid side",
    -1118: "EMPTY_NEW_CL_ORD_ID - New client order ID was empty",
    -1119: "EMPTY_ORG_CL_ORD_ID - Original client order ID was empty",
    -1120: "BAD_INTERVAL - Invalid interval",
    -1121: "BAD_SYMBOL - Invalid symbol",
    -1125: "INVALID_LISTEN_KEY - This listenKey does not exist",
    -1127: "MORE_THAN_XX_HOURS - Lookup interval is too big",
    -1128: "OPTIONAL_PARAMS_BAD_COMBO - Combination of optional parameters invalid",
    -1130: "INVALID_PARAMETER - Invalid data sent for a parameter",
    -1131: "BAD_RECV_WINDOW - recvWindow must be less than 60000",
    -2010: "NEW_ORDER_REJECTED - Order would immediately match and take",
    -2011: "CANCEL_REJECTED - Order cancel-replace partially failed",
    -2013: "NO_SUCH_ORDER - Order does not exist",
    -2014: "BAD_API_KEY_FMT - API-key format invalid",
    -2015: "REJECTED_MBX_KEY - Invalid API-key, IP, or permissions",
}


class BinanceErrorHandler:
    """Handles Binance API errors with retry logic and rate limiting"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.rate_limit_retry_after = None
    
    def handle_error(self, error: BinanceAPIException, context=""):
        """
        Handle Binance API exception
        
        Args:
            error: BinanceAPIException
            context: Additional context about where error occurred
        
        Returns:
            dict with error info and retry recommendation
        """
        error_code = error.code
        error_msg = ERROR_CODES.get(error_code, "Unknown error")
        
        self.logger.error(
            f"Binance API Error [{error_code}] {context}: {error_msg} - {error.message}"
        )
        
        # Determine if retryable
        retryable = error_code in [
            -1003,  # TOO_MANY_REQUESTS
            -1006,  # UNEXPECTED_RESP
            -1007,  # TIMEOUT
        ]
        
        # Check for rate limiting (HTTP 429)
        if error.status_code == 429:
            retry_after = int(error.response.headers.get('Retry-After', 60))
            self.rate_limit_retry_after = time.time() + retry_after
            self.logger.warning(f"Rate limited. Retry after {retry_after} seconds")
            retryable = True
        
        # Check weight limits (HTTP 418)
        if error.status_code == 418:
            retry_after = int(error.response.headers.get('Retry-After', 60))
            self.logger.warning(f"IP banned for exceeding rate limits. Retry after {retry_after}s")
            retryable = False  # Don't auto-retry on IP ban
        
        return {
            'error_code': error_code,
            'error_message': error_msg,
            'details': error.message,
            'retryable': retryable,
            'retry_after': self.rate_limit_retry_after
        }
    
    def is_rate_limited(self):
        """Check if currently rate limited"""
        if self.rate_limit_retry_after is None:
            return False
        return time.time() < self.rate_limit_retry_after
    
    def check_symbol_status(self, symbol_info):
        """
        Check if symbol is tradeable
        
        Args:
            symbol_info: Symbol info from exchange
        
        Returns:
            bool: True if tradeable
        """
        status = symbol_info.get('status')
        if status != 'TRADING':
            self.logger.warning(f"Symbol status is {status}, not TRADING")
            return False
        return True


def with_error_handling(func):
    """
    Decorator to add error handling to Binance API calls
    
    Usage:
        @with_error_handling
        def place_order(self, ...):
            return self.client.create_order(...)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        handler = BinanceErrorHandler()
        
        try:
            # Check if rate limited
            if handler.is_rate_limited():
                wait_time = handler.rate_limit_retry_after - time.time()
                handler.logger.warning(f"Rate limited, waiting {wait_time:.0f}s")
                time.sleep(wait_time)
            
            return func(*args, **kwargs)
        
        except BinanceAPIException as e:
            error_info = handler.handle_error(e, context=func.__name__)
            
            # Re-raise with context
            raise BinanceAPIException(
                response=e.response,
                status_code=e.status_code,
                text=f"{error_info['error_message']}: {error_info['details']}"
            )
    
    return wrapper


# Quick reference for common errors
COMMON_ERRORS = {
    'AUTHENTICATION': [
        "Make sure API keys are correct",
        "Check API key has spot trading permissions",
        "Verify IP whitelist if enabled",
        "Check system time is synchronized (NTP)"
    ],
    'RATE_LIMIT': [
        "Reduce request frequency",
        "Use WebSocket for real-time data instead of REST",
        "Implement exponential backoff",
        "Check X-MBX-USED-WEIGHT header"
    ],
    'ORDER_REJECTED': [
        "Check symbol is in TRADING status",
        "Verify order size meets minimum/maximum",
        "Check account has sufficient balance",
        "Validate price/quantity precision"
    ],
    'RECV_WINDOW': [
        "Ensure recvWindow < 60000ms",
        "Synchronize system clock with NTP",
        "Reduce network latency",
        "Use smaller recvWindow value"
    ]
}


def print_error_guide(error_type='ALL'):
    """Print troubleshooting guide for common errors"""
    if error_type == 'ALL':
        for category, tips in COMMON_ERRORS.items():
            print(f"\n{category} Issues:")
            for tip in tips:
                print(f"  - {tip}")
    elif error_type in COMMON_ERRORS:
        print(f"\n{error_type} Troubleshooting:")
        for tip in COMMON_ERRORS[error_type]:
            print(f"  - {tip}")
