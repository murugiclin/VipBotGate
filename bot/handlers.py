import logging
import os
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.models import PlanType, get_plan_configs
from bot.btc_api import get_btc_price, check_address_balance
from bot.utils import format_time_remaining, format_btc_amount
from bot.core.config import Config
from bot.services.payment_service import PaymentService
import database

logger = logging.getLogger(__name__)

async def handle_start(update, context):
    """Handle /start command"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Create/update user
    await database.create_user(user.id, user.username, user.first_name)

    welcome_text = f"Hello {user.first_name} 👋\nWelcome to our VIP service."

    keyboard = [
        [InlineKeyboardButton("📊 Compare Plans", callback_data="compare_plans")],
        [InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("❌ Cancel Plan", callback_data="cancel_plan")],
        [InlineKeyboardButton("🆘 Support", callback_data="support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_text,
        reply_markup=reply_markup
    )

async def handle_callback(update, context):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # Admin callbacks
    if data.startswith("admin_") or data.startswith("force_"):
        from bot.admin import handle_admin_callback
        await handle_admin_callback(query, context)
        return

    # Regular user callbacks
    if data == "compare_plans":
        await show_compare_plans(query, context)
    elif data == "dashboard":
        await show_dashboard(query, context)
    elif data == "cancel_plan":
        await cancel_plan(query, context)
    elif data == "support":
        await show_support(query, context)
    elif data.startswith("buy_"):
        plan_type = data.split("_")[1].upper()
        await initiate_purchase(query, context, PlanType(plan_type))
    elif data == "view_pending":
        await view_pending_transaction(query, context)
    elif data == "back_to_main":
        await back_to_main(query, context)
    elif data == "request_admin_access":
        await request_admin_access(query, context)
    elif data == "refresh":
        await handle_refresh(query, context) # Handle refresh callback
    elif data.startswith("copy_address_"):
        await handle_copy_address(query, context)

async def show_compare_plans(query, context):
    """Show plan comparison"""
    plans_text = "🎯 **Choose Your VIP Plan:**\n\n"

    for plan_type, config in get_plan_configs().items():
        duration = "Lifetime" if config["duration_days"] is None else f"{config['duration_days']} days"
        plans_text += f"{config['emoji']} **{config['name']}**: ${config['price_usd']} / {duration}\n"

    keyboard = []
    for plan_type, config in get_plan_configs().items():
        keyboard.append([InlineKeyboardButton(f"💳 Buy {config['name']} {config['emoji']}", callback_data=f"buy_{plan_type.name.lower()}")])

    keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=plans_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_dashboard(query, context):
    """Show user dashboard"""
    user_id = query.from_user.id

    # Get active subscription
    active_sub = await database.get_active_subscription(user_id)

    # Get user transactions
    transactions = await database.get_user_transactions(user_id)

    # Add timestamp to prevent "not modified" errors
    current_time = datetime.utcnow().strftime('%H:%M:%S')
    dashboard_text = f"💼 Your Dashboard (Updated: {current_time})\n\n"

    if active_sub:
        plan_config = get_plan_configs()[PlanType(active_sub['plan_type'])]
        vip_link = Config.VIP_LINKS.get(active_sub['plan_type'], "")

        dashboard_text += f"✅ Active Subscription:\n"
        dashboard_text += f"Plan: {plan_config['emoji']} {plan_config['name']}\n"
        dashboard_text += f"Status: Active\n"

        if active_sub['expires_at']:
            dashboard_text += f"Expires: {active_sub['expires_at'].strftime('%Y-%m-%d %H:%M')}\n"
        else:
            dashboard_text += f"Expires: Never (Lifetime)\n"

        if vip_link:
            dashboard_text += f"\n🔗 Your VIP Access: {vip_link}\n"
    else:
        dashboard_text += "❌ No Active Subscription\n"

    dashboard_text += "\n📊 Recent Transactions:\n"

    if transactions:
        for i, tx in enumerate(transactions[:3]):
            plan_config = get_plan_configs()[PlanType(tx['plan_type'])]
            status_emoji = {"pending": "⏳", "confirmed": "✅", "expired": "❌", "cancelled": "🚫"}

            dashboard_text += f"\n{i+1}. {plan_config['emoji']} {tx['plan_type']}\n"
            dashboard_text += f"   Amount: {format_btc_amount(float(tx['btc_amount']))} BTC (${float(tx['usd_amount']):.2f})\n"
            dashboard_text += f"   Status: {status_emoji.get(tx['status'], '❓')} {tx['status'].title()}\n"
            dashboard_text += f"   Date: {tx['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
    else:
        dashboard_text += "No transactions found.\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")], # Changed callback_data to "refresh"
        [InlineKeyboardButton("📌 View Pending", callback_data="view_pending")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            text=dashboard_text,
            reply_markup=reply_markup
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            await query.answer("Dashboard is already up to date.", show_alert=False)
        else:
            logger.error(f"Error updating dashboard: {e}")

async def cancel_plan(query, context):
    """Cancel pending transactions"""
    user_id = query.from_user.id

    transactions = await database.get_user_transactions(user_id)
    pending_transactions = [tx for tx in transactions if tx['status'] == 'pending']

    if not pending_transactions:
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="❌ No pending transactions to cancel.",
            reply_markup=reply_markup
        )
        return

    # Release addresses and cancel transactions
    for tx in pending_transactions:
        try:
            balance = await check_address_balance(tx['btc_address'])
            if balance == 0:
                await database.release_btc_address(tx['btc_address'])
        except Exception as e:
            logger.error(f"Error checking address balance: {e}")

        await database.update_transaction_status(tx['id'], 'cancelled')

    keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="✅ All pending transactions have been cancelled.",
        reply_markup=reply_markup
    )

async def show_support(query, context):
    """Show support information"""
    support_text = "🆘 **Support**\n\n"
    support_text += "For assistance, please contact our support team:\n"
    support_text += "@Tradcj\n\n"
    support_text += "Click the button below to start a chat."

    keyboard = [
        [InlineKeyboardButton("💬 Chat with Support", url="https://t.me/Tradcj")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=support_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def initiate_purchase(query, context, plan_type: PlanType):
    """Initiate purchase process"""
    user = query.from_user
    user_id = user.id

    # Ensure user exists in database first
    await database.create_user(user_id, user.username, user.first_name)

    # Get current BTC price
    btc_price = await get_btc_price()
    if not btc_price:
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="compare_plans")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="❌ Unable to fetch BTC price. Please try again later.",
            reply_markup=reply_markup
        )
        return

    # Check if user already has active subscription for this plan
    active_subscription = await database.get_active_subscription(user_id)
    if active_subscription and active_subscription['plan_type'] == plan_type:
        await query.edit_message_text(
            text=f"❌ You already have an active {plan_type} subscription!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")
            ]])
        )
        return

    # Check if user has pending transaction for this plan
    pending_tx = await database.get_pending_transaction(user_id)
    if pending_tx and pending_tx['plan_type'] == plan_type:
        # Show existing pending transaction
        await show_payment_details(query, context, pending_tx)
        return
    elif pending_tx:
        # Cancel old pending transaction for different plan
        await database.update_transaction_status(pending_tx['id'], 'cancelled')
        await database.release_btc_address(pending_tx['btc_address'])

    # Create payment using service
    payment = await PaymentService.create_payment(user_id, plan_type, btc_price)
    if not payment:
        await query.edit_message_text(
            text="❌ Unable to create payment. You may already have an active subscription or no addresses available.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Back", callback_data="compare_plans")
            ]])
        )
        return

    # Show payment details
    await show_payment_details(query, context, payment)

async def view_pending_transaction(query, context):
    """Show pending transaction details"""
    user_id = query.from_user.id

    transactions = await database.get_user_transactions(user_id)
    pending_transactions = [tx for tx in transactions if tx['status'] == 'pending']

    current_time = datetime.utcnow().strftime('%H:%M:%S')

    if not pending_transactions:
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(
                text=f"❌ No pending transactions found. (Updated: {current_time})",
                reply_markup=reply_markup
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error updating pending view: {e}")
        return

    tx = pending_transactions[0]
    plan_config = get_plan_configs()[PlanType(tx['plan_type'])]

    time_left = tx['expires_at'] - datetime.utcnow()

    if time_left.total_seconds() <= 0:
        status_text = "❌ Expired"
        time_text = "This payment has expired."
    else:
        status_text = "⏳ Pending Confirmation"
        time_text = f"Time Left: {format_time_remaining(time_left)}"

    pending_text = f"📌 **Pending Transaction** (Updated: {current_time})\n\n"
    pending_text += f"Plan: {plan_config['emoji']} {plan_config['name']}\n"
    pending_text += f"Amount: **{format_btc_amount(float(tx['btc_amount']))} BTC**\n"
    pending_text += f"Address:\n`{tx['btc_address']}`\n\n"
    pending_text += f"Status: {status_text}\n"
    pending_text += f"{time_text}\n\n"
    pending_text += f"💡 *Tap and hold the address above to copy, or use the Copy button below*\n"
    pending_text += f"Created: {tx['created_at'].strftime('%Y-%m-%d %H:%M')}"

    keyboard = [
        [InlineKeyboardButton("📋 Copy Address", callback_data=f"copy_address_{tx['id']}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="view_pending")],
        [InlineKeyboardButton("❌ Cancel Transaction", callback_data="cancel_plan")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            text=pending_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            await query.answer("Transaction status is up to date.", show_alert=False)
        else:
            logger.error(f"Error updating pending transaction: {e}")

async def request_admin_access(query, context):
    """Handle admin access request"""
    user = query.from_user
    admin_id = int(os.getenv("ADMIN_USER_ID", 0))

    request_text = "🔐 **Admin Access Request**\n\n"
    request_text += "To become an admin and control signals in groups, you must meet these requirements:\n\n"
    request_text += "✅ Have more than $5,000 USD in your trading account\n"
    request_text += "✅ Have 3+ years of trading experience\n\n"
    request_text += "Please contact our admin with your achievements, trading experience, and what you can offer to the community."

    keyboard = [
        [InlineKeyboardButton("💬 Contact Admin", url=f"https://t.me/{os.getenv('SUPPORT_USERNAME', 'tradecj')}")],
        [InlineKeyboardButton("⬅ Back", callback_data="dashboard")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Also notify admin about the request
    try:
        admin_notification = f"🔔 **New Admin Access Request**\n\n"
        admin_notification += f"User: {user.first_name} {user.last_name or ''}\n"
        admin_notification += f"Username: @{user.username or 'no_username'}\n"
        admin_notification += f"User ID: {user.id}\n"
        admin_notification += f"Requested at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"

        await context.bot.send_message(
            chat_id=admin_id,
            text=admin_notification,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify admin about access request: {e}")

    await query.edit_message_text(
        text=request_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def back_to_main(query, context):
    """Return to main menu"""
    user = query.from_user
    welcome_text = f"Hello {user.first_name} 👋\nWelcome to our VIP service."

    keyboard = [
        [InlineKeyboardButton("📊 Compare Plans", callback_data="compare_plans")],
        [InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("❌ Cancel Plan", callback_data="cancel_plan")],
        [InlineKeyboardButton("🆘 Support", callback_data="support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=welcome_text,
        reply_markup=reply_markup
    )

async def handle_refresh(query, context):
    """Handle refresh button for both user and admin"""
    user_id = query.from_user.id

    try:
        if query.data == 'refresh':
            # User refresh - show dashboard
            await show_dashboard(query, context)
        elif query.data == 'admin_pending':
            # Admin refresh - show pending transactions
            await show_pending_transactions(query, context)
        elif query.data == 'admin_users':
            # Admin refresh - show users
            await show_users(query, context)
        elif query.data == 'admin_transactions':
            # Admin refresh - show transactions
            await show_transactions(query, context)
    except Exception as e:
        if "not modified" in str(e).lower():
            # Silently ignore "message not modified" errors
            await query.answer("Already up to date", show_alert=False)
        else:
            logger.error(f"Refresh error: {e}")
            await query.answer("❌ Refresh failed", show_alert=True)

async def initiate_purchase(query, context, plan_type: PlanType):
    """Initiate purchase process"""
    user = query.from_user
    user_id = user.id

    # Ensure user exists in database first
    await database.create_user(user_id, user.username, user.first_name)

    # Get current BTC price
    btc_price = await get_btc_price()
    if not btc_price:
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="compare_plans")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text="❌ Unable to fetch BTC price. Please try again later.",
            reply_markup=reply_markup
        )
        return

    # Check if user already has active subscription for this plan
    active_subscription = await database.get_active_subscription(user_id)
    if active_subscription and active_subscription['plan_type'] == plan_type:
        await query.edit_message_text(
            text=f"❌ You already have an active {plan_type} subscription!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")
            ]])
        )
        return

    # Check if user has pending transaction for this plan
    pending_tx = await database.get_pending_transaction(user_id)
    if pending_tx and pending_tx['plan_type'] == plan_type:
        # Show existing pending transaction
        await show_payment_details(query, context, pending_tx)
        return
    elif pending_tx:
        # Cancel old pending transaction for different plan
        await database.update_transaction_status(pending_tx['id'], 'cancelled')
        await database.release_btc_address(pending_tx['btc_address'])

    # Create payment using service
    payment = await PaymentService.create_payment(user_id, plan_type, btc_price)
    if not payment:
        await query.edit_message_text(
            text="❌ Unable to create payment. You may already have an active subscription or no addresses available.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Back", callback_data="compare_plans")
            ]])
        )
        return

    # Show payment details
    await show_payment_details(query, context, payment)

async def handle_copy_address(query, context):
    """Handle copy address button click"""
    try:
        transaction_id = int(query.data.split("_")[2])
        transaction = await database.get_transaction(transaction_id)
        
        if transaction:
            # Send the address as a separate message for easy copying
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"📋 **Copy this address:**\n\n`{transaction['btc_address']}`\n\n💡 *Tap and hold the address above to copy it*",
                parse_mode='Markdown'
            )
            await query.answer("Address sent below - tap and hold to copy!", show_alert=False)
        else:
            await query.answer("Transaction not found", show_alert=True)
    except Exception as e:
        logger.error(f"Error handling copy address: {e}")
        await query.answer("Error copying address", show_alert=True)

async def show_payment_details(query, context, payment):
    """Show payment details to the user"""
    plan_config = get_plan_configs()[PlanType(payment['plan_type'])]

    payment_text = f"💳 **Payment Required**\n\n"
    payment_text += f"Plan: {plan_config['emoji']} {plan_config['name']}\n"
    payment_text += f"Amount: {format_btc_amount(payment['btc_amount'])} BTC (${payment['usd_amount']:.2f})\n"
    payment_text += f"BTC Rate: ${payment['btc_price']:,.2f}\n\n"
    payment_text += f"Send exactly **{format_btc_amount(payment['btc_amount'])} BTC** to:\n\n"
    payment_text += f"`{payment['btc_address']}`\n\n"
    payment_text += f"⏰ Expires in {Config.PAYMENT_TIMEOUT_MINUTES} minutes\n"
    payment_text += f"💡 *Tap and hold the address above to copy, or use the Copy button below*\n"
    payment_text += f"Payment will be automatically detected."

    keyboard = [
        [InlineKeyboardButton("📋 Copy Address", callback_data=f"copy_address_{payment['id']}")],
        [InlineKeyboardButton("📌 View Pending Transaction", callback_data="view_pending")],
        [InlineKeyboardButton("⬅ Back", callback_data="compare_plans")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=payment_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )