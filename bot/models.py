from enum import Enum
from typing import Dict, Any, Optional

class PlanType(Enum):
    """VIP Plan types"""
    VIP1 = "VIP1"
    VIP2 = "VIP2"
    VIP3 = "VIP3"

class TransactionStatus(Enum):
    """Transaction status types"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class SubscriptionStatus(Enum):
    """Subscription status types"""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

def get_plan_configs() -> Dict[PlanType, Dict[str, Any]]:
    """Get plan configurations with links from environment"""
    from bot.core.config import Config
    
    return {
        PlanType.VIP1: {
            "name": "VIP1 Plan",
            "emoji": "🥉",
            "price_usd": 50.0,
            "duration_days": 30,
            "link": Config.VIP_LINKS.get("VIP1", ""),
            "description": "Basic VIP access with standard features",
            "features": [
                "✅ Basic signals",
                "✅ Community access", 
                "✅ Email support"
            ]
        },
        PlanType.VIP2: {
            "name": "VIP2 Plan",
            "emoji": "🥈", 
            "price_usd": 100.0,
            "duration_days": 30,
            "link": Config.VIP_LINKS.get("VIP2", ""),
            "description": "Premium VIP access with advanced features",
            "features": [
                "✅ Premium signals",
                "✅ Priority community access",
                "✅ Live chat support",
                "✅ Weekly analysis"
            ]
        },
        PlanType.VIP3: {
            "name": "VIP3 Plan",
            "emoji": "🥇",
            "price_usd": 200.0,
            "duration_days": None,  # Lifetime
            "link": Config.VIP_LINKS.get("VIP3", ""),
            "description": "Ultimate VIP access with all features",
            "features": [
                "✅ Ultimate signals",
                "✅ VIP community access", 
                "✅ 24/7 priority support",
                "✅ Daily analysis",
                "✅ 1-on-1 consultation",
                "✅ Risk management tools"
            ]
        }
    }

# Dynamic plan configs
PLAN_CONFIGS = get_plan_configs()

def get_plan_config(plan_type: PlanType) -> Dict[str, Any]:
    """Get plan configuration"""
    return PLAN_CONFIGS.get(plan_type, {})

def get_all_plans() -> Dict[PlanType, Dict[str, Any]]:
    """Get all plan configurations"""
    return PLAN_CONFIGS

def validate_plan_type(plan_type_str: str) -> Optional[PlanType]:
    """Validate and return PlanType from string"""
    try:
        return PlanType(plan_type_str.upper())
    except ValueError:
        return None