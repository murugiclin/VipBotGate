import os
import asyncio
import logging
import signal
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging with security
class SecureFormatter(logging.Formatter):
    """Custom formatter to mask sensitive information"""
    def format(self, record):
        if hasattr(record, 'msg') and record.msg:
            msg = str(record.msg)
            bot_token = os.getenv("BOT_TOKEN", "")
            if bot_token and bot_token in msg:
                msg = msg.replace(bot_token, f"{bot_token[:10]}***MASKED***")
            record.msg = msg
        return super().format(record)

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('bot.log')
        ]
    )

    # Reduce telegram library verbosity
    logging.getLogger('telegram').setLevel(logging.ERROR)
    logging.getLogger('httpx').setLevel(logging.ERROR)
    logging.getLogger('asyncio').setLevel(logging.ERROR)
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('aiohttp').setLevel(logging.ERROR)

    # Filter out spam logs
    class CustomFilter(logging.Filter):
        def filter(self, record):
            message = record.getMessage().lower()

            # Filter out telegram "not modified" errors
            if "message is not modified" in message:
                return False
            if "specified new message content" in message:
                return False
            if "exactly the same as a current content" in message:
                return False

            # Filter out connection noise
            if "connection pool is closed" in message and record.levelno < logging.ERROR:
                return False
            if "ssl" in message and record.levelno < logging.WARNING:
                return False

            return True

    logging.getLogger().addFilter(CustomFilter())

setup_logging()
logger = logging.getLogger(__name__)

# Import after logging setup
try:
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import database
    from bot.handlers import handle_start, handle_callback
    from bot.admin import handle_admin
    from bot.payment_checker import check_payments_job
except ImportError as e:
    logger.error(f"Import error: {e}")
    exit(1)

class TelegramBot:
    def __init__(self):
        self.app = None
        self.scheduler = None
        self.stop_event = asyncio.Event()

    async def initialize(self):
        """Initialize bot components"""
        # Validate environment
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN not found in environment")

        logger.info(f"Initializing bot with token: {bot_token[:10]}***MASKED***")

        # Initialize database
        await database.init_database()
        logger.info("Database initialized successfully")

        # Create application
        self.app = Application.builder().token(bot_token).build()

        # Add error handler
        self.app.add_error_handler(self._error_handler)

        # Add handlers
        self.app.add_handler(CommandHandler("start", handle_start))
        self.app.add_handler(CommandHandler("admin", handle_admin))
        self.app.add_handler(CallbackQueryHandler(handle_callback))

        # Setup scheduler
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            check_payments_job,
            'interval',
            minutes=20,
            args=[self.app.bot]
        )
        # Add alert checks every 5 minutes for responsive alerts
        from bot.payment_checker import run_all_alert_checks
        self.scheduler.add_job(
            run_all_alert_checks,
            'interval', 
            minutes=5,
            args=[self.app.bot]
        )

    async def _error_handler(self, update, context):
        """Global error handler"""
        error_msg = str(context.error)

        # Don't log "not modified" errors as they're expected
        if "not modified" not in error_msg.lower():
            logger.error(f"Bot error: {error_msg}")
            import traceback
            logger.debug(f"Full traceback: {traceback.format_exc()}")

            if update and update.effective_chat:
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="❌ An error occurred. Please try again later."
                    )
                except:
                    pass

    async def start(self):
        """Start the bot"""
        try:
            await self.initialize()

            # Start scheduler
            self.scheduler.start()
            logger.info("Payment scheduler started")

            # Start bot
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)

            logger.info("Bot started successfully")

            # Setup signal handlers
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda s, f: self.stop_event.set())

            # Wait for stop signal
            await self.stop_event.wait()

        except Exception as e:
            logger.error(f"Bot startup error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot gracefully"""
        logger.info("Stopping bot...")

        if self.scheduler:
            self.scheduler.shutdown()

        if self.app:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except:
                pass

async def main():
    """Main entry point"""
    bot = TelegramBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main())