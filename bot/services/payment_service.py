
import logging
from datetime import datetime, timedelta
from typing import Optional
from bot.models import PlanType, get_plan_configs
from bot.core.config import Config
import database

logger = logging.getLogger(__name__)

class PaymentService:
    """Handle payment-related business logic"""
    
    @staticmethod
    async def create_payment(user_id: int, plan_type: PlanType, btc_price: float) -> Optional[dict]:
        """Create a new payment transaction"""
        try:
            # Check for existing active subscription
            active_sub = await database.get_active_subscription(user_id)
            if active_sub:
                return None
                
            # Get BTC address
            btc_address = await database.get_next_btc_address(user_id)
            if not btc_address:
                return None
                
            # Calculate amounts
            plan_config = get_plan_configs()[plan_type]
            usd_amount = plan_config["price_usd"]
            btc_amount = usd_amount / btc_price
            
            # Create transaction
            expires_at = datetime.utcnow() + timedelta(minutes=Config.PAYMENT_TIMEOUT_MINUTES)
            tx_id = await database.create_transaction(
                user_id, plan_type.value, btc_address, btc_amount, usd_amount, btc_price, expires_at
            )
            
            return {
                "id": tx_id,
                "plan_type": plan_type.value,
                "btc_address": btc_address,
                "btc_amount": btc_amount,
                "usd_amount": usd_amount,
                "btc_price": btc_price,
                "expires_at": expires_at
            }
            
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            return None
    
    @staticmethod
    async def confirm_payment(transaction: dict) -> bool:
        """Confirm a payment and create subscription"""
        try:
            # Update transaction status
            await database.update_transaction_status(transaction['id'], 'confirmed', datetime.utcnow())
            
            # Create subscription
            plan_type = transaction['plan_type']
            expires_at = None
            
            plan_config = get_plan_configs()[PlanType(plan_type)]
            if plan_config["duration_days"]:
                expires_at = datetime.utcnow() + timedelta(days=plan_config["duration_days"])
            
            await database.create_subscription(
                transaction['user_id'], 
                plan_type, 
                transaction['id'], 
                expires_at
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error confirming payment: {e}")
            return False
