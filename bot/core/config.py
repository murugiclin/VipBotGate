
import os
from typing import List

class Config:
    """Bot configuration"""
    
    # Bot settings
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
    SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "tradecj")
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/vip_bot")
    
    # Bitcoin settings
    BTC_ADDRESSES = [
        addr.strip() for addr in os.getenv("BTC_ADDRESSES", "").split(",") 
        if addr.strip()
    ]
    
    # VIP Links - NO HARDCODED VALUES
    VIP_LINKS = {
        "VIP1": os.getenv("VIP1_LINK", ""),
        "VIP2": os.getenv("VIP2_LINK", ""), 
        "VIP3": os.getenv("VIP3_LINK", "")
    }
    
    # Payment settings
    PAYMENT_TIMEOUT_MINUTES = 30
    PAYMENT_CHECK_INTERVAL_MINUTES = 5
    
    @classmethod
    def validate(cls) -> List[str]:
        """Validate configuration and return errors"""
        errors = []
        
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is required")
            
        if not cls.ADMIN_USER_ID:
            errors.append("ADMIN_USER_ID is required")
            
        if not cls.BTC_ADDRESSES:
            errors.append("BTC_ADDRESSES is required")
            
        return errors
