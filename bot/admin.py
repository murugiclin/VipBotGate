
import os
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.models import PlanType, PLAN_CONFIGS
from bot.utils import format_btc_amount, format_currency, format_username, calculate_percentage
import database

logger = logging.getLogger(__name__)

async def handle_admin(update, context):
    """Handle /admin command"""
    user_id = update.effective_user.id
    admin_id = int(os.getenv("ADMIN_USER_ID", 0))
    
    if user_id != admin_id:
        await update.message.reply_text("❌ Access denied. Admin only.")
        return
    
    welcome_text = f"👑 **Admin Panel**\n\nWelcome {update.effective_user.first_name}!"
    
    keyboard = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Total Profits", callback_data="admin_profits")],
        [InlineKeyboardButton("⏳ Pending Transactions", callback_data="admin_pending")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔧 Force Actions", callback_data="admin_force")],
        [InlineKeyboardButton("🔔 Alerts", callback_data="admin_alerts")],
        [InlineKeyboardButton("⬅ Back to Bot", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text=welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_admin_callback(query, context):
    """Handle admin callback queries"""
    data = query.data
    user_id = query.from_user.id
    admin_id = int(os.getenv("ADMIN_USER_ID", 0))
    
    if user_id != admin_id:
        await query.answer("❌ Access denied", show_alert=True)
        return
    
    if data == "admin_users":
        await show_all_users(query, context)
    elif data == "admin_profits":
        await show_total_profits(query, context)
    elif data == "admin_pending":
        await show_pending_transactions(query, context)
    elif data == "admin_stats":
        await show_statistics(query, context)
    elif data == "admin_force":
        await show_force_actions(query, context)
    elif data == "admin_alerts":
        await show_alerts(query, context)
    elif data == "admin_plan_breakdown":
        await show_plan_breakdown(query, context)
    elif data.startswith("force_approve_"):
        tx_id = int(data.split("_")[2])
        await force_approve_transaction(query, context, tx_id)
    elif data.startswith("force_reject_"):
        tx_id = int(data.split("_")[2])
        await force_reject_transaction(query, context, tx_id)
    elif data == "admin_back":
        await admin_main_menu(query, context)

async def show_all_users(query, context):
    """Show all users with their data"""
    users_data = await database.get_all_users()
    
    users_text = "👥 **All Users**\n\n"
    users_text += f"```\n{'ID':<8} {'Username':<12} {'Plan':<6} {'Status':<10} {'BTC':<12}\n"
    users_text += "-" * 55 + "\n"
    
    for user in users_data[:20]:  # Show first 20 users
        user_id = str(user['user_id'])[:8]
        username = format_username(user['username'])[:12]
        plan = user.get('plan_type', 'None')[:6]
        status = user.get('status', 'N/A')[:10]
        btc_amount = format_btc_amount(float(user.get('btc_amount', 0)))[:12]
        
        users_text += f"{user_id:<8} {username:<12} {plan:<6} {status:<10} {btc_amount:<12}\n"
    
    users_text += "```"
    
    if len(users_data) > 20:
        users_text += f"\n... and {len(users_data) - 20} more users"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_users")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=users_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_total_profits(query, context):
    """Show total profits and revenue"""
    profits = await database.get_total_profits()
    
    total_btc = float(profits.get('total_btc', 0))
    total_usd = float(profits.get('total_usd', 0))
    total_transactions = profits.get('count', 0)
    
    # Get current BTC price for live conversion
    from bot.btc_api import get_btc_price
    current_btc_price = await get_btc_price()
    current_btc_value = total_btc * current_btc_price if current_btc_price else 0
    
    profits_text = "💰 **Total Profits**\n\n"
    profits_text += f"📊 **Summary:**\n"
    profits_text += f"Total Transactions: {total_transactions}\n"
    profits_text += f"Total BTC Received: {format_btc_amount(total_btc)}\n"
    profits_text += f"Total USD (at payment): {format_currency(total_usd)}\n\n"
    
    if current_btc_price:
        profits_text += f"💹 **Current Values:**\n"
        profits_text += f"BTC Price: {format_currency(current_btc_price)}\n"
        profits_text += f"Current BTC Value: {format_currency(current_btc_value)}\n"
        
        profit_loss = current_btc_value - total_usd
        profit_emoji = "📈" if profit_loss >= 0 else "📉"
        profits_text += f"{profit_emoji} P&L: {format_currency(profit_loss)}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_profits")],
        [InlineKeyboardButton("📊 Plan Breakdown", callback_data="admin_plan_breakdown")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=profits_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_pending_transactions(query, context):
    """Show all pending transactions with real-time data"""
    pending_txs = await database.get_pending_transactions()
    
    current_time = datetime.utcnow().strftime('%H:%M:%S')
    pending_text = f"⏳ **Pending Transactions** (Updated: {current_time})\n\n"
    
    if not pending_txs:
        pending_text += "No pending transactions."
    else:
        for i, tx in enumerate(pending_txs[:10], 1):
            plan_config = PLAN_CONFIGS[PlanType(tx['plan_type'])]
            time_left = tx['expires_at'] - datetime.utcnow()
            
            pending_text += f"**{i}. Transaction #{tx['id']}**\n"
            pending_text += f"User: {tx['user_id']}\n"
            pending_text += f"Plan: {plan_config['emoji']} {plan_config['name']}\n"
            pending_text += f"Amount: {format_btc_amount(float(tx['btc_amount']))} BTC\n"
            pending_text += f"Address: `{tx['btc_address']}`\n"
            
            if time_left.total_seconds() > 0:
                minutes_left = int(time_left.total_seconds() // 60)
                pending_text += f"Expires in: {minutes_left}m\n"
            else:
                pending_text += f"Status: ❌ Expired\n"
            
            pending_text += "\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_pending")],
        [InlineKeyboardButton("🔧 Force Actions", callback_data="admin_force")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
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
            await query.answer("Data is already up to date.", show_alert=False)
        else:
            logger.error(f"Error updating admin pending: {e}")

async def show_statistics(query, context):
    """Show detailed statistics"""
    # Get plan popularity stats
    async with database.pool.acquire() as conn:
        plan_stats = await conn.fetch("""
            SELECT plan_type, COUNT(*) as count, SUM(usd_amount) as total_usd
            FROM transactions WHERE status = 'confirmed'
            GROUP BY plan_type
        """)
        
        # Get user activity by day
        activity_stats = await conn.fetch("""
            SELECT DATE(created_at) as date, COUNT(*) as signups
            FROM users
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        
        # Get conversion rate
        total_signups = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_payments = await conn.fetchval("SELECT COUNT(*) FROM transactions WHERE status = 'confirmed'")
    
    stats_text = "📊 **Statistics**\n\n"
    
    # Plan popularity
    stats_text += "📈 **Plan Popularity:**\n"
    total_sales = sum(row['count'] for row in plan_stats)
    
    for row in plan_stats:
        plan_config = PLAN_CONFIGS[PlanType(row['plan_type'])]
        percentage = calculate_percentage(row['count'], total_sales)
        stats_text += f"{plan_config['emoji']} {row['plan_type']}: {row['count']} ({percentage:.1f}%)\n"
    
    # Conversion rate
    conversion_rate = calculate_percentage(total_payments, total_signups) if total_signups > 0 else 0
    stats_text += f"\n💹 **Conversion Rate:** {conversion_rate:.1f}%\n"
    stats_text += f"Total Signups: {total_signups}\n"
    stats_text += f"Total Payments: {total_payments}\n"
    
    # Recent activity
    stats_text += f"\n📅 **Recent Activity (7 days):**\n"
    for row in activity_stats:
        stats_text += f"{row['date']}: {row['signups']} signups\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=stats_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_force_actions(query, context):
    """Show force approve/reject options"""
    pending_txs = await database.get_pending_transactions()
    
    force_text = "🔧 **Force Actions**\n\n"
    force_text += "Select a transaction to approve or reject:\n\n"
    
    keyboard = []
    
    for tx in pending_txs[:5]:  # Show first 5 transactions
        plan_config = PLAN_CONFIGS[PlanType(tx['plan_type'])]
        tx_info = f"#{tx['id']} - {plan_config['emoji']} {tx['plan_type']} - {format_btc_amount(float(tx['btc_amount']))} BTC"
        
        keyboard.extend([
            [InlineKeyboardButton(f"✅ Approve {tx_info}", callback_data=f"force_approve_{tx['id']}")],
            [InlineKeyboardButton(f"❌ Reject {tx_info}", callback_data=f"force_reject_{tx['id']}")]
        ])
    
    if not pending_txs:
        force_text += "No pending transactions to manage."
    
    keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=force_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def force_approve_transaction(query, context, tx_id: int):
    """Force approve a transaction"""
    try:
        # Get transaction details
        async with database.pool.acquire() as conn:
            tx = await conn.fetchrow("SELECT * FROM transactions WHERE id = $1", tx_id)
        
        if not tx:
            await query.answer("Transaction not found", show_alert=True)
            return
        
        if tx['status'] != 'pending':
            await query.answer("Transaction is not pending", show_alert=True)
            return
        
        # Force approve
        await database.update_transaction_status(tx_id, 'confirmed', datetime.utcnow())
        
        # Create subscription
        plan_type = tx['plan_type']
        expires_at = None
        
        if PLAN_CONFIGS[PlanType(plan_type)]["duration_days"]:
            expires_at = datetime.utcnow() + timedelta(days=PLAN_CONFIGS[PlanType(plan_type)]["duration_days"])
        
        await database.create_subscription(tx['user_id'], plan_type, tx_id, expires_at)
        
        # Notify user with proper confirmation message
        from bot.core.config import Config
        from bot.models import get_plan_configs
        
        plan_configs = get_plan_configs()
        plan_config = plan_configs[PlanType(plan_type)]
        vip_link = Config.VIP_LINKS.get(plan_type, "")
        
        confirmation_text = f"✅ Payment Approved by Admin!\n\n"
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
            [InlineKeyboardButton("💼 Dashboard", callback_data="dashboard")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=tx['user_id'],
            text=confirmation_text,
            reply_markup=reply_markup
        )
        
        await query.answer("✅ Transaction approved successfully!", show_alert=True)
        await show_force_actions(query, context)
        
    except Exception as e:
        logger.error(f"Error force approving transaction {tx_id}: {e}")
        await query.answer("❌ Error approving transaction", show_alert=True)

async def force_reject_transaction(query, context, tx_id: int):
    """Force reject a transaction"""
    try:
        # Get transaction details
        async with database.pool.acquire() as conn:
            tx = await conn.fetchrow("SELECT * FROM transactions WHERE id = $1", tx_id)
        
        if not tx:
            await query.answer("Transaction not found", show_alert=True)
            return
        
        if tx['status'] != 'pending':
            await query.answer("Transaction is not pending", show_alert=True)
            return
        
        # Force reject
        await database.update_transaction_status(tx_id, 'cancelled')
        
        # Release BTC address
        await database.release_btc_address(tx['btc_address'])
        
        # Notify user
        reject_text = f"❌ Payment Rejected\n\n"
        reject_text += f"Your payment for {PLAN_CONFIGS[PlanType(tx['plan_type'])]['name']} has been rejected by admin.\n"
        reject_text += f"Please contact support if you believe this is an error."
        
        await context.bot.send_message(
            chat_id=tx['user_id'],
            text=reject_text
        )
        
        await query.answer("❌ Transaction rejected successfully!", show_alert=True)
        await show_force_actions(query, context)
        
    except Exception as e:
        logger.error(f"Error force rejecting transaction {tx_id}: {e}")
        await query.answer("❌ Error rejecting transaction", show_alert=True)

async def show_plan_breakdown(query, context):
    """Show plan breakdown statistics"""
    async with database.pool.acquire() as conn:
        plan_stats = await conn.fetch("""
            SELECT plan_type, 
                   COUNT(*) as total_transactions,
                   COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed,
                   COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                   COUNT(CASE WHEN status = 'expired' THEN 1 END) as expired,
                   COALESCE(SUM(CASE WHEN status = 'confirmed' THEN usd_amount END), 0) as revenue
            FROM transactions 
            GROUP BY plan_type
            ORDER BY revenue DESC
        """)
    
    breakdown_text = "📊 **Plan Breakdown**\n\n"
    
    for stat in plan_stats:
        plan_config = PLAN_CONFIGS[PlanType(stat['plan_type'])]
        breakdown_text += f"{plan_config['emoji']} **{plan_config['name']}**\n"
        breakdown_text += f"Total Transactions: {stat['total_transactions']}\n"
        breakdown_text += f"✅ Confirmed: {stat['confirmed']}\n"
        breakdown_text += f"⏳ Pending: {stat['pending']}\n"
        breakdown_text += f"❌ Expired: {stat['expired']}\n"
        breakdown_text += f"💰 Revenue: {format_currency(float(stat['revenue']))}\n\n"
    
    if not plan_stats:
        breakdown_text += "No transaction data available."
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_plan_breakdown")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_profits")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=breakdown_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_alerts(query, context):
    """Show admin alerts and notifications"""
    alerts_text = "🔔 **Admin Alerts**\n\n"
    
    # Get users who started but haven't paid within 10 minutes
    async with database.pool.acquire() as conn:
        unpaid_users = await conn.fetch("""
            SELECT u.user_id, u.first_name, u.username, u.created_at
            FROM users u
            LEFT JOIN transactions t ON u.user_id = t.user_id
            WHERE u.created_at >= CURRENT_TIMESTAMP - INTERVAL '10 minutes'
            AND (t.id IS NULL OR t.status = 'pending')
            ORDER BY u.created_at DESC
        """)
        
        # Get recent expired transactions
        expired_recent = await conn.fetch("""
            SELECT user_id, plan_type, btc_amount, expires_at
            FROM transactions
            WHERE status = 'expired' 
            AND expires_at >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
            ORDER BY expires_at DESC
        """)
    
    if unpaid_users:
        alerts_text += f"⚠️ **Users Started but Not Paid (10min):**\n"
        for user in unpaid_users[:5]:
            alerts_text += f"• {user['first_name']} (@{user['username'] or 'no_username'}) - {user['user_id']}\n"
        alerts_text += "\n"
    
    if expired_recent:
        alerts_text += f"⏰ **Recently Expired (1hr):**\n"
        for tx in expired_recent[:5]:
            plan_config = PLAN_CONFIGS[PlanType(tx['plan_type'])]
            alerts_text += f"• {plan_config['emoji']} {tx['plan_type']} - {format_btc_amount(float(tx['btc_amount']))} BTC\n"
        alerts_text += "\n"
    
    if not unpaid_users and not expired_recent:
        alerts_text += "✅ No recent alerts."
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_alerts")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=alerts_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_main_menu(query, context):
    """Return to admin main menu"""
    welcome_text = f"👑 **Admin Panel**\n\nWelcome {query.from_user.first_name}!"
    
    keyboard = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Total Profits", callback_data="admin_profits")],
        [InlineKeyboardButton("⏳ Pending Transactions", callback_data="admin_pending")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔧 Force Actions", callback_data="admin_force")],
        [InlineKeyboardButton("🔔 Alerts", callback_data="admin_alerts")],
        [InlineKeyboardButton("⬅ Back to Bot", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
