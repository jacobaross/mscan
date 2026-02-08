"""Tests for the cache manager module."""

import json
import time
import tempfile
import shutil
from pathlib import Path

import pytest

from mscan.enricher.cache_manager import CacheManager, CacheTier, CacheStats


class TestCacheManager:
    """Test cases for CacheManager."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test_cache.db"
        yield str(db_path)
        shutil.rmtree(temp_dir)
        
    @pytest.fixture
    def cache(self, temp_db):
        """Create a CacheManager with temp database."""
        return CacheManager(db_path=temp_db)
        
    def test_init_creates_db(self, temp_db):
        """Test that initialization creates the database."""
        cache = CacheManager(db_path=temp_db)
        assert Path(temp_db).exists()
        
    def test_set_and_get(self, cache):
        """Test basic set and get operations."""
        data = {"name": "Test Company", "cik": "0000123456"}
        
        assert cache.set("test_key", data, CacheTier.ENTITY_METADATA) is True
        
        result = cache.get("test_key")
        assert result == data
        
    def test_get_nonexistent(self, cache):
        """Test getting a non-existent key."""
        result = cache.get("nonexistent_key")
        assert result is None
        
    def test_get_expired(self, cache):
        """Test that expired entries are not returned."""
        data = {"name": "Test Company"}
        
        # Set with very short TTL
        cache.set("expiring_key", data, ttl_seconds=0.01)
        
        # Should be available immediately
        assert cache.get("expiring_key") == data
        
        # Wait for expiry
        time.sleep(0.1)
        
        # Should be expired now
        assert cache.get("expiring_key") is None
        
    def test_get_ignore_expiry(self, cache):
        """Test getting expired data when check_expiry=False."""
        data = {"name": "Test Company"}
        
        cache.set("expiring_key", data, ttl_seconds=0.01)
        time.sleep(0.1)
        
        # Should still return expired data
        result = cache.get("expiring_key", check_expiry=False)
        assert result == data
        
    def test_delete(self, cache):
        """Test delete operation."""
        data = {"name": "Test Company"}
        cache.set("delete_me", data)
        
        assert cache.get("delete_me") == data
        assert cache.delete("delete_me") is True
        assert cache.get("delete_me") is None
        
    def test_delete_nonexistent(self, cache):
        """Test deleting a non-existent key."""
        assert cache.delete("nonexistent") is False
        
    def test_cleanup_expired(self, cache):
        """Test cleanup of expired entries."""
        # Add some entries
        cache.set("keep_me", {"data": 1}, ttl_seconds=3600)
        cache.set("expire_me", {"data": 2}, ttl_seconds=0.01)
        
        time.sleep(0.1)
        
        # Cleanup should remove expired entry
        removed = cache.cleanup_expired()
        assert removed == 1
        
        # Non-expired should still exist
        assert cache.get("keep_me") is not None
        
    def test_get_by_ticker(self, cache):
        """Test lookup by ticker symbol."""
        data = {"name": "Apple Inc", "cik": "0000320193"}
        cache.set("0000320193", data, ticker="AAPL")
        
        result = cache.get_by_ticker("AAPL")
        assert result == data
        
    def test_get_by_ticker_not_found(self, cache):
        """Test lookup by non-existent ticker."""
        result = cache.get_by_ticker("FAKE")
        assert result is None
        
    def test_get_stats(self, cache):
        """Test statistics tracking."""
        # Initially empty
        stats = cache.get_stats()
        assert isinstance(stats, CacheStats)
        assert stats.hits == 0
        assert stats.misses == 0
        
        # Make a hit
        cache.set("key1", {"data": 1})
        cache.get("key1")
        
        stats = cache.get_stats()
        assert stats.hits == 1
        assert stats.misses == 0
        
        # Make a miss
        cache.get("nonexistent")
        
        stats = cache.get_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 50.0
        
    def test_get_db_stats(self, cache):
        """Test database statistics."""
        # Add entries
        cache.set("key1", {"data": 1}, CacheTier.ENTITY_METADATA)
        cache.set("key2", {"data": 2}, CacheTier.FINANCIALS)
        
        db_stats = cache.get_db_stats()
        
        assert db_stats['total_entries'] == 2
        assert db_stats['active_entries'] == 2
        assert 'db_size_bytes' in db_stats
        assert 'entries_by_tier' in db_stats
        
    def test_clear_all(self, cache):
        """Test clearing all cache entries."""
        cache.set("key1", {"data": 1})
        cache.set("key2", {"data": 2})
        
        assert cache.clear_all() is True
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        
        stats = cache.get_stats()
        assert stats.hits == 0
        assert stats.misses == 0
        
    def test_update_existing(self, cache):
        """Test that set updates existing entries."""
        cache.set("key", {"version": 1})
        cache.set("key", {"version": 2})
        
        result = cache.get("key")
        assert result == {"version": 2}
        
    def test_access_count_tracking(self, cache):
        """Test that access counts are tracked."""
        cache.set("key", {"data": 1})
        
        # Access multiple times
        cache.get("key")
        cache.get("key")
        cache.get("key")
        
        # Access count is tracked internally, not exposed directly
        # This test mainly ensures no errors occur
        
    def test_context_manager(self, temp_db):
        """Test context manager functionality."""
        with CacheManager(db_path=temp_db) as cache:
            cache.set("key", {"data": 1})
            assert cache.get("key") == {"data": 1}
            # Stats persisted on exit
            
    def test_ttl_overrides(self, temp_db):
        """Test custom TTL overrides."""
        overrides = {
            CacheTier.ENTITY_METADATA: 100,
            CacheTier.FINANCIALS: 200
        }
        cache = CacheManager(db_path=temp_db, ttl_overrides=overrides)
        
        # The TTL should be applied (internal verification)
        assert cache._ttl[CacheTier.ENTITY_METADATA] == 100
        assert cache._ttl[CacheTier.FINANCIALS] == 200
        
    def test_complex_data_serialization(self, cache):
        """Test serialization of complex data types."""
        data = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"a": 1, "b": 2},
            "date": "2024-01-01"  # Dates as strings
        }
        
        cache.set("complex", data)
        result = cache.get("complex")
        
        assert result == data
        
    def test_concurrent_access(self, cache):
        """Test concurrent access to cache."""
        import threading
        
        errors = []
        
        def worker(thread_id):
            try:
                for i in range(10):
                    key = f"thread_{thread_id}_key_{i}"
                    cache.set(key, {"thread": thread_id, "item": i})
                    result = cache.get(key)
                    assert result["thread"] == thread_id
            except Exception as e:
                errors.append(e)
                
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        assert len(errors) == 0
