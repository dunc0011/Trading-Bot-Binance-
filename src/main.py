"""
Binance Trading Bot - Main Entry Point
"""
import os
import sys
import asyncio
import logging
from dotenv import load_dotenv
from colorlog import ColoredFormatter

from bot import TradingBot
from config.config import Config

# Load environment variables
load_dotenv()


def setup_logging(log_level: str = "INFO"):
    """Configure colored logging."""
    formatter = ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(message)s",
        datefmt=None,
        reset=True,
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    logger = logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, log_level.upper()))

    return logger


async def main():
    """Main bot execution."""
    config = Config()
    logger = setup_logging(config.log_level)
    
    logger.info("=" * 50)
    logger.info("Binance Trading Bot Starting...")
    logger.info("=" * 50)
    logger.info(f"Mode: {config.trading_mode.upper()}")
    logger.info(f"Symbol: {config.symbol}")
    logger.info(f"Timeframe: {config.timeframe}")
    logger.info(f"Dry Run: {config.dry_run}")
    logger.info("=" * 50)
    
    if not config.dry_run:
        logger.warning("⚠️  LIVE TRADING MODE - Real money at risk!")
        response = input("Type 'CONFIRM' to proceed with live trading: ")
        if response != "CONFIRM":
            logger.info("Live trading cancelled by user")
            return
    
    try:
        bot = TradingBot(config)
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
