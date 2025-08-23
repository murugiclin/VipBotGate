
import re
from datetime import timedelta
from typing import Optional

def format_btc_amount(amount: float) -> str:
    """Format BTC amount with proper precision"""
    if amount >= 1:
        return f"{amount:.6f}"
    elif amount >= 0.001:
        return f"{amount:.8f}"
    else:
        return f"{amount:.10f}"

def format_time_remaining(time_left: timedelta) -> str:
    """Format time remaining in human readable format"""
    if time_left.total_seconds() <= 0:
        return "Expired"
    
    total_seconds = int(time_left.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def format_username(username: Optional[str]) -> str:
    """Format username with @ prefix or return 'N/A'"""
    if username:
        return f"@{username}" if not username.startswith('@') else username
    return "N/A"

def validate_btc_address(address: str) -> bool:
    """Basic BTC address validation"""
    # Basic regex for BTC addresses (simplified)
    btc_pattern = r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$|^bc1[a-z0-9]{39,59}$'
    return bool(re.match(btc_pattern, address))

def format_currency(amount: float, currency: str = "USD") -> str:
    """Format currency with proper formatting"""
    if currency == "USD":
        return f"${amount:,.2f}"
    elif currency == "BTC":
        return f"{format_btc_amount(amount)} BTC"
    else:
        return f"{amount:.2f} {currency}"

def truncate_address(address: str, chars: int = 8) -> str:
    """Truncate BTC address for display"""
    if len(address) <= chars * 2:
        return address
    return f"{address[:chars]}...{address[-chars:]}"

def calculate_percentage(part: float, total: float) -> float:
    """Calculate percentage safely"""
    if total == 0:
        return 0.0
    return (part / total) * 100
def format_time_remaining(time_delta):
    """Format time remaining in a readable format"""
    total_seconds = int(time_delta.total_seconds())
    
    if total_seconds <= 0:
        return "Expired"
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def format_btc_amount(amount):
    """Format BTC amount with appropriate precision"""
    if amount >= 1:
        return f"{amount:.4f}"
    elif amount >= 0.001:
        return f"{amount:.6f}"
    else:
        return f"{amount:.8f}"

def format_currency(amount):
    """Format currency amount"""
    return f"${amount:,.2f}"

def format_username(username):
    """Format username for display"""
    if not username:
        return "no_username"
    return f"@{username}"

def calculate_percentage(part, total):
    """Calculate percentage"""
    if total == 0:
        return 0
    return (part / total) * 100
