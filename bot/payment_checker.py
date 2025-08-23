import os
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.models import PlanType, get_plan_configs
from bot.btc_api import check_address_balance
from bot.utils import format_btc_amount
from bot.core.config import Config
import database

logger = logging.getLogger(__name__)

async def check_payments_job(bot):
    """Check all pending payments"""
    logger.info("Checking payments...")

    try:
        pending_txs = await database.get_pending_transactions()

        for tx in pending_txs:
            await check_single_payment(bot, tx)

        await handle_expired_transactions(bot)

    except Exception as e:
        logger.error(f"Error in payment check: {e}")

async def check_single_payment(bot, tx):
    """Check a single payment"""
    try:
        balance = await check_address_balance(tx['btc_address'])
        expected_amount = float(tx['btc_amount'])

        if balance >= expected_amount:
            # Check for double spending
            from bot.btc_api import check_double_spend
            is_double_spend = await check_double_spend(tx['btc_address'], expected_amount)

            if is_double_spend:
                logger.warning(f"Double spend detected for transaction {tx['id']}")
                await notify_admin_double_spend(bot, tx)
                return

            await confirm_payment(bot, tx)
        elif balance > 0 and balance < expected_amount:
            # Partial payment - notify user
            await notify_partial_payment(bot, tx, balance, expected_amount)

    except Exception as e:
        logger.error(f"Error checking payment {tx['id']}: {e}")

async def notify_partial_payment(bot, tx, received_amount: float, expected_amount: float):
    """Notify user about partial payment"""
    try:
        difference = expected_amount - received_amount

        partial_text = f"⚠️ *Partial Payment Detected*\n\n"
        partial_text += f"We received: {format_btc_amount(received_amount)} BTC\n"
        partial_text += f"Expected: {format_btc_amount(expected_amount)} BTC\n"
        partial_text += f"Missing: {format_btc_amount(difference)} BTC\n\n"
        partial_text += f"Please send the remaining amount to complete your payment.\n"
        partial_text += f"Address: `{tx['btc_address']}`"

        await bot.send_message(
            chat_id=tx['user_id'],
            text=partial_text,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error notifying partial payment for tx {tx['id']}: {e}")

async def notify_admin_double_spend(bot, tx):
    """Notify admin about potential double spend"""
    try:
        admin_id = int(os.getenv("ADMIN_USER_ID", 0))

        alert_text = f"🚨 *DOUBLE SPEND ALERT*\n\n"
        alert_text += f"Transaction ID: {tx['id']}\n"
        alert_text += f"User ID: {tx['user_id']}\n"
        alert_text += f"Address: `{tx['btc_address']}`\n"
        alert_text += f"Amount: {format_btc_amount(float(tx['btc_amount']))} BTC\n"
        alert_text += f"Plan: {tx['plan_type']}\n\n"
        alert_text += f"⚠️ Potential double spending detected. Manual review required."

        await bot.send_message(
            chat_id=admin_id,
            text=alert_text,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error notifying admin about double spend: {e}")

async def notify_admin_unpaid_users(bot):
    """Notify admin about users who started but haven't paid"""
    try:
        admin_id = int(os.getenv("ADMIN_USER_ID", 0))

        # Get users who started but haven't paid within 10 minutes
        async with database.pool.acquire() as conn:
            unpaid_users = await conn.fetch("""
                SELECT u.user_id, u.first_name, u.username, u.created_at
                FROM users u
                LEFT JOIN transactions t ON u.user_id = t.user_id
                WHERE u.created_at >= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                AND u.created_at <= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                AND (t.id IS NULL OR t.status = 'pending')
                ORDER BY u.created_at DESC
                LIMIT 5
            """)

        if unpaid_users:
            alert_text = f"⏰ *Unpaid Users Alert*\n\n"
            alert_text += f"Users who started 10 minutes ago but haven't paid:\n\n"

            for user in unpaid_users:
                alert_text += f"• {user['first_name']} (@{user['username'] or 'no_username'})\n"
                alert_text += f"  ID: {user['user_id']}\n"
                alert_text += f"  Started: {user['created_at'].strftime('%H:%M')}\n\n"

            await bot.send_message(
                chat_id=admin_id,
                text=alert_text,
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error notifying admin about unpaid users: {e}")

async def confirm_payment(bot, tx):
    """Confirm payment and create subscription"""
    try:
        # Update transaction
        await database.update_transaction_status(tx['id'], 'confirmed', datetime.utcnow())

        # Create subscription
        plan_type = tx['plan_type']
        expires_at = None

        plan_configs = get_plan_configs() # Use the dynamic function
        if plan_configs[PlanType(plan_type)]["duration_days"]:
            expires_at = datetime.utcnow() + timedelta(days=plan_configs[PlanType(plan_type)]["duration_days"])

        await database.create_subscription(tx['user_id'], plan_type, tx['id'], expires_at)

        # Get VIP link for this specific plan only
        vip_link = Config.VIP_LINKS.get(plan_type, "")
        plan_config = plan_configs[PlanType(plan_type)] # Use the dynamic function

        confirmation_text = f"✅ Payment Confirmed!\n\n"
        confirmation_text += f"Welcome to {plan_config['emoji']} {plan_config['name']}!\n\n"
        confirmation_text += f"💰 Amount: {format_btc_amount(float(tx['btc_amount']))} BTC\n"

        if plan_config["duration_days"]:
            expires_date = datetime.utcnow() + timedelta(days=plan_config["duration_days"])
            confirmation_text += f"⏰ Expires: {expires_date.strftime('%Y-%m-%d')}\n"
        else:
            confirmation_text += f"⏰ Duration: Lifetime\n"

        if vip_link:
            confirmation_text += f"\n🔗 Your VIP Access:\n{vip_link}\n"

        confirmation_text += f"\n🎉 Welcome to the community!"

        keyboard = [
            [InlineKeyboardButton("🔐 Request Admin Access", callback_data="admin_access")],
            [InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=tx['user_id'],
            text=confirmation_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error confirming payment {tx['id']}: {e}")

async def send_double_spend_reminder(bot, user_id, plan_type):
    """Send reminder 40 minutes after confirmation to avoid double spending"""
    try:
        plan_configs = get_plan_configs()
        plan_config = plan_configs[PlanType(plan_type)]
        
        reminder_text = f"🔔 **Important Reminder**\n\n"
        reminder_text += f"Your {plan_config['name']} payment was confirmed 40 minutes ago.\n\n"
        reminder_text += f"⚠️ **Please do not send any additional payments** for this plan to avoid double spending.\n\n"
        reminder_text += f"Your subscription is already active!"
        
        await bot.send_message(chat_id=user_id, text=reminder_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Failed to send double spend reminder to {user_id}: {e}")

async def get_plan_popularity_stats():
    """Get plan popularity statistics"""
    try:
        async with database.pool.acquire() as conn:
            stats = await conn.fetch("""
                SELECT plan_type, COUNT(*) as count
                FROM transactions 
                WHERE status = 'confirmed'
                GROUP BY plan_type
            """)
            
            total = sum(row['count'] for row in stats)
            if total == 0:
                return "No confirmed transactions yet."
            
            plan_configs = get_plan_configs()
            stats_text = f"📊 **Plan Popularity Stats:**\n\n"
            for row in stats:
                percentage = (row['count'] / total) * 100
                plan_config = plan_configs[PlanType(row['plan_type'])]
                stats_text += f"{plan_config['name']}: {row['count']} ({percentage:.1f}%)\n"
            
            stats_text += f"\nTotal: {total} confirmed transactions"
            return stats_text
            
    except Exception as e:
        logger.error(f"Error getting plan stats: {e}")
        return "Error retrieving statistics."

async def get_user_activity_heatmap():
    """Get user activity heatmap by hour"""
    try:
        async with database.pool.acquire() as conn:
            activity = await conn.fetch("""
                SELECT EXTRACT(hour FROM last_activity) as hour, COUNT(*) as count
                FROM users
                WHERE last_activity >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                GROUP BY EXTRACT(hour FROM last_activity)
                ORDER BY hour
            """)
            
            if not activity:
                return "No recent user activity data."
            
            heatmap_text = f"🕐 **User Activity Heatmap (Last 7 Days):**\n\n"
            
            # Create simple bar chart with activity by hour
            for row in activity:
                hour = int(row['hour'])
                count = row['count']
                bar = "█" * min(count, 20)  # Max 20 chars for bar
                heatmap_text += f"{hour:02d}:00 {bar} {count}\n"
            
            return heatmap_text
            
    except Exception as e:
        logger.error(f"Error getting activity heatmap: {e}")
        return "Error retrieving activity data."

async def run_all_alert_checks(bot):
    """Run all alert checks - main alert function"""
    # Check for unpaid users (10 minutes)
    await notify_admin_unpaid_users(bot)
    
    # Check for double spend reminders (40 minutes after confirmation)
    try:
        forty_minutes_ago = datetime.utcnow() - timedelta(minutes=40)
        five_minutes_window = datetime.utcnow() - timedelta(minutes=35)
        
        async with database.pool.acquire() as conn:
            reminder_txs = await conn.fetch("""
                SELECT user_id, plan_type FROM transactions
                WHERE status = 'confirmed' 
                AND confirmed_at BETWEEN $1 AND $2
            """, forty_minutes_ago, five_minutes_window)
        
        for tx in reminder_txs:
            await send_double_spend_reminder(bot, tx['user_id'], tx['plan_type'])
            
    except Exception as e:
        logger.error(f"Error sending double spend reminders: {e}")

async def handle_expired_transactions(bot):
    """Handle expired transactions"""
    try:
        # Get expired transactions
        async with database.pool.acquire() as conn:
            expired_txs = await conn.fetch(
                "SELECT * FROM transactions WHERE status = 'pending' AND expires_at <= CURRENT_TIMESTAMP"
            )

        for tx in expired_txs:
            try:
                # Check if address has balance
                balance = await check_address_balance(tx['btc_address'])

                if balance == 0:
                    await database.release_btc_address(tx['btc_address'])

                await database.update_transaction_status(tx['id'], 'expired')

                # Notify user
                expiry_text = f"⏰ *Payment Expired*\n\n"
                plan_configs = get_plan_configs() # Use the dynamic function
                expiry_text += f"Your payment for {plan_configs[PlanType(tx['plan_type'])]['name']} has expired.\n"
                expiry_text += f"Please start again with /start"

                await bot.send_message(
                    chat_id=tx['user_id'],
                    text=expiry_text,
                    parse_mode='Markdown'
                )

            except Exception as e:
                logger.error(f"Error handling expired transaction {tx['id']}: {e}")

    except Exception as e:
        logger.error(f"Error handling expired transactions: {e}")