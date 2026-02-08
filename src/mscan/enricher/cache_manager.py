"""SQLite-based cache manager for SEC EDGAR data.

Provides persistent caching with TTL support, cache hit/miss tracking,
and automatic cleanup of expired entries.
"""

import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)


class CacheTier(Enum):
    """Cache tiers with different TTL values."""
    ENTITY_METADATA = "entity_metadata"      # 7 days
    FINANCIALS = "financials"                # 30 days
    FILINGS_LIST = "filings_list"            # 1 day
    TICKER_MAPPING = "ticker_mapping"        # 7 days
    COMPANY_FACTS = "company_facts"          # 30 days


# Default TTL values in seconds
DEFAULT_TTL = {
    CacheTier.ENTITY_METADATA: 7 * 24 * 3600,      # 7 days
    CacheTier.FINANCIALS: 30 * 24 * 3600,          # 30 days
    CacheTier.FILINGS_LIST: 24 * 3600,             # 1 day
    CacheTier.TICKER_MAPPING: 7 * 24 * 3600,       # 7 days
    CacheTier.COMPANY_FACTS: 30 * 24 * 3600,       # 30 days
}


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    errors: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
    
    @property
    def total_requests(self) -> int:
        """Total cache requests (hits + misses)."""
        return self.hits + self.misses


@dataclass 
class CacheEntry:
    """Represents a cached data entry."""
    key: str
    data: Dict[str, Any]
    tier: CacheTier
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None


class CacheManager:
    """SQLite-based cache manager for SEC EDGAR API data.
    
    Provides persistent caching with:
    - TTL-based expiration per data type
    - Cache hit/miss tracking
    - Automatic cleanup of expired entries
    - JSON serialization for complex data types
    - Thread-safe operations
    
    Args:
        db_path: Path to SQLite database file. Default: ~/.mscan/edgar_cache.db
        ttl_overrides: Optional dict to override default TTL values.
        
    Example:
        >>> cache = CacheManager()
        >>> cache.set("0000320193", {"name": "Apple Inc"}, CacheTier.ENTITY_METADATA)
        >>> data = cache.get("0000320193")
        >>> stats = cache.get_stats()
        >>> print(f"Hit rate: {stats.hit_rate:.1f}%")
    """
    
    def __init__(
        self,
        db_path: str = "~/.mscan/edgar_cache.db",
        ttl_overrides: Optional[Dict[CacheTier, int]] = None
    ):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build TTL config
        self._ttl = DEFAULT_TTL.copy()
        if ttl_overrides:
            self._ttl.update(ttl_overrides)
        
        # In-memory stats (not persisted)
        self._stats = CacheStats()
        
        # Initialize database
        self._init_db()
        
        logger.info(f"CacheManager initialized: {self.db_path}")
    
    def _init_db(self):
        """Initialize SQLite schema with proper indexing."""
        with self._get_connection() as conn:
            # Main cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edgar_cache (
                    key TEXT PRIMARY KEY,
                    ticker TEXT,
                    company_name TEXT,
                    tier TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP
                )
            """)
            
            # Indices for efficient queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ticker ON edgar_cache(ticker)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires ON edgar_cache(expires_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_company_name ON edgar_cache(company_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tier ON edgar_cache(tier)
            """)
            
            # Stats table for persisted metrics
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    persisted_hits INTEGER DEFAULT 0,
                    persisted_misses INTEGER DEFAULT 0,
                    last_cleanup TIMESTAMP
                )
            """)
            
            # Initialize stats row if not exists
            conn.execute("""
                INSERT OR IGNORE INTO cache_stats (id) VALUES (1)
            """)
            
            conn.commit()
            
        logger.debug("Database schema initialized")
    
    @contextmanager
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def get(
        self,
        key: str,
        check_expiry: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached data by key.
        
        Args:
            key: Cache key (typically CIK number).
            check_expiry: If True, return None for expired entries.
                         If False, return expired data anyway.
                         
        Returns:
            Cached data dict if found and not expired, None otherwise.
        """
        try:
            with self._get_connection() as conn:
                if check_expiry:
                    row = conn.execute(
                        """
                        SELECT data, expires_at, access_count 
                        FROM edgar_cache 
                        WHERE key = ? AND expires_at > datetime('now')
                        """,
                        (key,)
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT data, expires_at, access_count FROM edgar_cache WHERE key = ?",
                        (key,)
                    ).fetchone()
                
                if row:
                    # Update access stats
                    conn.execute(
                        """
                        UPDATE edgar_cache 
                        SET access_count = ?, last_accessed = datetime('now')
                        WHERE key = ?
                        """,
                        (row['access_count'] + 1, key)
                    )
                    conn.commit()
                    
                    self._stats.hits += 1
                    logger.debug(f"Cache hit for key: {key}")
                    return json.loads(row['data'])
                else:
                    self._stats.misses += 1
                    logger.debug(f"Cache miss for key: {key}")
                    return None
                    
        except sqlite3.Error as e:
            self._stats.errors += 1
            logger.error(f"Cache get error for key {key}: {e}")
            return None
    
    def set(
        self,
        key: str,
        data: Dict[str, Any],
        tier: CacheTier = CacheTier.ENTITY_METADATA,
        ttl_seconds: Optional[int] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None
    ) -> bool:
        """Store data in cache.
        
        Args:
            key: Cache key (typically CIK number).
            data: Data to cache (must be JSON-serializable).
            tier: Cache tier determining default TTL.
            ttl_seconds: Override TTL (seconds). Uses tier default if None.
            ticker: Optional ticker symbol for indexing.
            company_name: Optional company name for indexing.
            
        Returns:
            True if successfully cached, False on error.
        """
        try:
            # Calculate expiration
            ttl = ttl_seconds if ttl_seconds is not None else self._ttl.get(tier, 86400)
            expires_at = datetime.now() + timedelta(seconds=ttl)
            
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO edgar_cache 
                    (key, ticker, company_name, tier, data, expires_at, access_count, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (
                        key,
                        ticker,
                        company_name,
                        tier.value,
                        json.dumps(data),
                        expires_at.isoformat()
                    )
                )
                conn.commit()
                
            self._stats.sets += 1
            logger.debug(f"Cached data for key: {key} (expires: {expires_at})")
            return True
            
        except (sqlite3.Error, TypeError) as e:
            self._stats.errors += 1
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete a specific cache entry.
        
        Args:
            key: Cache key to delete.
            
        Returns:
            True if entry existed and was deleted, False otherwise.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM edgar_cache WHERE key = ?",
                    (key,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    self._stats.deletes += 1
                    logger.debug(f"Deleted cache entry: {key}")
                    return True
                return False
                
        except sqlite3.Error as e:
            self._stats.errors += 1
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """Remove all expired cache entries.
        
        Returns:
            Number of entries removed.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM edgar_cache WHERE expires_at <= datetime('now')"
                )
                conn.commit()
                
                removed = cursor.rowcount
                if removed > 0:
                    self._stats.evictions += removed
                    logger.info(f"Cleaned up {removed} expired cache entries")
                
                # Update last cleanup timestamp
                conn.execute(
                    "UPDATE cache_stats SET last_cleanup = datetime('now') WHERE id = 1"
                )
                conn.commit()
                
                return removed
                
        except sqlite3.Error as e:
            self._stats.errors += 1
            logger.error(f"Cache cleanup error: {e}")
            return 0
    
    def get_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Lookup cache entry by ticker symbol.
        
        Args:
            ticker: Stock ticker symbol.
            
        Returns:
            Cached data if found, None otherwise.
        """
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT key FROM edgar_cache 
                    WHERE ticker = ? AND expires_at > datetime('now')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (ticker.upper(),)
                ).fetchone()
                
                if row:
                    return self.get(row['key'])
                return None
                
        except sqlite3.Error as e:
            logger.error(f"Cache lookup by ticker error: {e}")
            return None
    
    def get_stats(self) -> CacheStats:
        """Get current cache statistics.
        
        Returns:
            CacheStats with current hit/miss metrics.
        """
        # Include persisted stats
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT persisted_hits, persisted_misses FROM cache_stats WHERE id = 1"
                ).fetchone()
                
                if row:
                    return CacheStats(
                        hits=self._stats.hits + row['persisted_hits'],
                        misses=self._stats.misses + row['persisted_misses'],
                        sets=self._stats.sets,
                        deletes=self._stats.deletes,
                        evictions=self._stats.evictions,
                        errors=self._stats.errors
                    )
        except sqlite3.Error:
            pass
            
        return CacheStats(
            hits=self._stats.hits,
            misses=self._stats.misses,
            sets=self._stats.sets,
            deletes=self._stats.deletes,
            evictions=self._stats.evictions,
            errors=self._stats.errors
        )
    
    def get_db_stats(self) -> Dict[str, Any]:
        """Get database-level statistics.
        
        Returns:
            Dict with entry counts, size, and age statistics.
        """
        try:
            with self._get_connection() as conn:
                # Total entries
                total = conn.execute(
                    "SELECT COUNT(*) as count FROM edgar_cache"
                ).fetchone()['count']
                
                # Expired entries
                expired = conn.execute(
                    "SELECT COUNT(*) as count FROM edgar_cache WHERE expires_at <= datetime('now')"
                ).fetchone()['count']
                
                # By tier
                tiers = conn.execute(
                    """
                    SELECT tier, COUNT(*) as count 
                    FROM edgar_cache 
                    GROUP BY tier
                    """
                ).fetchall()
                
                # Database file size
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
                
                # Oldest and newest entries
                oldest = conn.execute(
                    "SELECT MIN(created_at) as date FROM edgar_cache"
                ).fetchone()['date']
                
                newest = conn.execute(
                    "SELECT MAX(created_at) as date FROM edgar_cache"
                ).fetchone()['date']
                
                return {
                    'total_entries': total,
                    'expired_entries': expired,
                    'active_entries': total - expired,
                    'entries_by_tier': {row['tier']: row['count'] for row in tiers},
                    'db_size_bytes': db_size,
                    'db_size_mb': round(db_size / (1024 * 1024), 2),
                    'oldest_entry': oldest,
                    'newest_entry': newest,
                }
                
        except sqlite3.Error as e:
            logger.error(f"Error getting DB stats: {e}")
            return {}
    
    def clear_all(self) -> bool:
        """Clear all cache entries.
        
        Returns:
            True if successful, False otherwise.
        """
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM edgar_cache")
                conn.execute(
                    "UPDATE cache_stats SET persisted_hits = 0, persisted_misses = 0 WHERE id = 1"
                )
                conn.commit()
                
            logger.info("Cache cleared")
            self._stats = CacheStats()
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    def persist_stats(self):
        """Persist current in-memory stats to database."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE cache_stats 
                    SET persisted_hits = persisted_hits + ?,
                        persisted_misses = persisted_misses + ?
                    WHERE id = 1
                    """,
                    (self._stats.hits, self._stats.misses)
                )
                conn.commit()
                
            # Reset in-memory counters
            self._stats.hits = 0
            self._stats.misses = 0
            
        except sqlite3.Error as e:
            logger.error(f"Error persisting stats: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - persist stats."""
        self.persist_stats()
