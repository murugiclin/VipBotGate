
import os
import asyncpg
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
pool = None

async def init_database():
    """Initialize database with connection pooling"""
    global pool
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost/vip_bot")
    
    try:
        pool = await asyncpg.create_pool(
            database_url,
            min_size=10,
            max_size=50,
            command_timeout=60,
            max_inactive_connection_lifetime=300
        )
        
        await create_tables()
        await init_btc_addresses()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Try fallback connection for development
        try:
            pool = await asyncpg.create_pool(
                "postgresql://postgres:password@localhost:5432/vip_bot",
                min_size=1,
                max_size=5
            )
            await create_tables()
            await init_btc_addresses()
            logger.info("Database initialized with fallback connection")
        except Exception as fallback_error:
            logger.error(f"Fallback database connection failed: {fallback_error}")
            raise

async def create_tables():
    """Create database tables"""
    async with pool.acquire() as conn:        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                first_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS btc_addresses (
                address VARCHAR(255) PRIMARY KEY,
                is_used BOOLEAN DEFAULT FALSE,
                assigned_to BIGINT,
                assigned_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                plan_type VARCHAR(10) NOT NULL,
                btc_address VARCHAR(255) NOT NULL,
                btc_amount DECIMAL(16,8) NOT NULL,
                usd_amount DECIMAL(10,2) NOT NULL,
                btc_rate DECIMAL(12,2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                confirmed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                plan_type VARCHAR(10) NOT NULL,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
            CREATE INDEX IF NOT EXISTS idx_transactions_address ON transactions(btc_address);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
            CREATE INDEX IF NOT EXISTS idx_btc_addresses_used ON btc_addresses(is_used);
        """)

async def init_btc_addresses():
    """Initialize BTC addresses from environment or file"""
    addresses = []
    
    # First try to load from file (for large address pools)
    addresses_file = os.getenv("BTC_ADDRESSES_FILE", "btc_addresses.txt")
    if os.path.exists(addresses_file):
        try:
            with open(addresses_file, 'r') as f:
                file_addresses = [line.strip() for line in f.readlines() if line.strip()]
                addresses.extend(file_addresses)
            logger.info(f"Loaded {len(file_addresses)} addresses from {addresses_file}")
        except Exception as e:
            logger.error(f"Error loading addresses from file: {e}")
    
    # Then try environment variable (for smaller pools)
    env_addresses = os.getenv("BTC_ADDRESSES", "").split(",")
    env_addresses = [addr.strip() for addr in env_addresses if addr.strip()]
    if env_addresses:
        addresses.extend(env_addresses)
        logger.info(f"Loaded {len(env_addresses)} addresses from environment")
    
    if not addresses:
        logger.warning("No BTC addresses found in environment or file")
        return
    
    # Batch insert for better performance with large address pools
    async with pool.acquire() as conn:
        batch_size = 1000  # Process 1000 addresses at a time
        
        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i + batch_size]
            
            # Use executemany for batch insertion
            await conn.executemany(
                "INSERT INTO btc_addresses (address) VALUES ($1) ON CONFLICT DO NOTHING",
                [(addr,) for addr in batch]
            )
            
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(addresses)-1)//batch_size + 1}")
    
    logger.info(f"Successfully initialized {len(addresses)} BTC addresses")

async def create_user(user_id: int, username: str, first_name: str):
    """Create or update user"""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, last_activity)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_activity = CURRENT_TIMESTAMP
        """, user_id, username, first_name)

async def get_user(user_id: int) -> Optional[Dict]:
    """Get user by ID"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None

async def get_available_btc_address() -> Optional[str]:
    """Get an available BTC address"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT address FROM btc_addresses 
            WHERE is_used = FALSE 
            ORDER BY RANDOM() 
            LIMIT 1
        """)
        return row['address'] if row else None

async def assign_btc_address(address: str, user_id: int) -> bool:
    """Assign BTC address to user"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE btc_addresses 
            SET is_used = TRUE, assigned_to = $1, assigned_at = CURRENT_TIMESTAMP
            WHERE address = $2 AND is_used = FALSE
        """, user_id, address)
        return result != "UPDATE 0"

async def release_btc_address(address: str):
    """Release BTC address for reuse"""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE btc_addresses 
            SET is_used = FALSE, assigned_to = NULL, assigned_at = NULL
            WHERE address = $1
        """, address)

async def create_transaction(user_id: int, plan_type: str, btc_address: str, 
                           btc_amount: float, usd_amount: float, btc_rate: float, 
                           expires_at: datetime = None) -> int:
    """Create transaction"""
    if expires_at is None:
        expires_at = datetime.utcnow() + timedelta(minutes=30)
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO transactions (user_id, plan_type, btc_address, btc_amount, 
                                    usd_amount, btc_rate, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, user_id, plan_type, btc_address, btc_amount, usd_amount, btc_rate, expires_at)
        return row['id']

async def get_transaction(transaction_id: int) -> Optional[Dict]:
    """Get transaction by ID"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM transactions WHERE id = $1", transaction_id)
        return dict(row) if row else None

async def get_user_transactions(user_id: int) -> List[Dict]:
    """Get all transactions for user"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM transactions WHERE user_id = $1 ORDER BY created_at DESC
        """, user_id)
        return [dict(row) for row in rows]

async def get_pending_transactions() -> List[Dict]:
    """Get all pending transactions"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM transactions 
            WHERE status = 'pending' 
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in rows]

async def update_transaction_status(transaction_id: int, status: str, confirmed_at: datetime = None):
    """Update transaction status"""
    async with pool.acquire() as conn:
        if confirmed_at:
            await conn.execute("""
                UPDATE transactions 
                SET status = $1, confirmed_at = $2 
                WHERE id = $3
            """, status, confirmed_at, transaction_id)
        else:
            await conn.execute("""
                UPDATE transactions 
                SET status = $1 
                WHERE id = $2
            """, status, transaction_id)

async def expire_old_transactions():
    """Mark expired transactions"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            UPDATE transactions 
            SET status = 'expired' 
            WHERE status = 'pending' AND expires_at < CURRENT_TIMESTAMP
            RETURNING btc_address
        """)
        
        # Release expired addresses
        for row in rows:
            await release_btc_address(row['btc_address'])
        
        return len(rows)

async def create_subscription(user_id: int, plan_type: str, transaction_id: int, expires_at: Optional[datetime]):
    """Create subscription"""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO subscriptions (user_id, plan_type, transaction_id, expires_at)
            VALUES ($1, $2, $3, $4)
        """, user_id, plan_type, transaction_id, expires_at)

async def get_active_subscription(user_id: int) -> Optional[Dict]:
    """Get user's active subscription"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM subscriptions 
            WHERE user_id = $1 AND status = 'active' 
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            ORDER BY created_at DESC LIMIT 1
        """, user_id)
        return dict(row) if row else None

async def expire_subscriptions():
    """Mark expired subscriptions"""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE subscriptions 
            SET status = 'expired' 
            WHERE status = 'active' 
            AND expires_at IS NOT NULL 
            AND expires_at < CURRENT_TIMESTAMP
        """)
        return int(result.split()[-1]) if result != "UPDATE 0" else 0

async def get_all_users() -> List[Dict]:
    """Get all users with transaction data"""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.username, u.first_name, u.created_at,
                   t.plan_type, t.status, t.btc_amount
            FROM users u 
            LEFT JOIN transactions t ON u.user_id = t.user_id
            ORDER BY u.created_at DESC
        """)
        return [dict(row) for row in rows]

async def get_total_profits() -> Dict:
    """Get total profits"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) as count, 
                   COALESCE(SUM(btc_amount), 0) as total_btc, 
                   COALESCE(SUM(usd_amount), 0) as total_usd
            FROM transactions WHERE status = 'confirmed'
        """)
        return dict(row) if row else {'count': 0, 'total_btc': 0, 'total_usd': 0}

async def get_next_btc_address(user_id: int) -> Optional[str]:
    """Get next available BTC address for user"""
    async with pool.acquire() as conn:
        # Check if user has any pending transactions first
        existing = await conn.fetchval("""
            SELECT btc_address FROM transactions 
            WHERE user_id = $1 AND status = 'pending'
            LIMIT 1
        """, user_id)
        
        if existing:
            return None  # User already has pending transaction
        
        # Get available address
        address = await get_available_btc_address()
        if address:
            success = await assign_btc_address(address, user_id)
            if success:
                return address
        return None

async def get_pending_transaction(user_id: int) -> Optional[Dict]:
    """Get user's pending transaction"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM transactions 
            WHERE user_id = $1 AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, user_id)
        return dict(row) if row else None

async def get_transaction_by_address(address: str) -> Optional[Dict]:
    """Get pending transaction by BTC address"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM transactions 
            WHERE btc_address = $1 AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, address)
        return dict(row) if row else None

async def cleanup_database():
    """Clean up expired data"""
    try:
        expired_txs = await expire_old_transactions()
        expired_subs = await expire_subscriptions()
        
        if expired_txs > 0 or expired_subs > 0:
            logger.info(f"Cleaned up {expired_txs} expired transactions and {expired_subs} expired subscriptions")
    
    except Exception as e:
        logger.error(f"Database cleanup failed: {e}")

async def get_user_batch(user_ids: list) -> List[Dict]:
    """Get multiple users in one query for better performance"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE user_id = ANY($1)", 
            user_ids
        )
        return [dict(row) for row in rows]

async def create_users_batch(users: List[Dict]):
    """Create multiple users in one transaction"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany("""
                INSERT INTO users (user_id, username, first_name, last_activity)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_activity = CURRENT_TIMESTAMP
            """, [(u['user_id'], u['username'], u['first_name']) for u in users])

# Health check
async def health_check() -> bool:
    """Check database health"""
    try:
        if not pool:
            return False
        
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
