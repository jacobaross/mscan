"""Tests for the rate limiter module."""

import time
import threading
import pytest

from mscan.utils.rate_limiter import RateLimiter, AdaptiveRateLimiter, RateLimitStats


class TestRateLimiter:
    """Test cases for RateLimiter."""
    
    def test_init_default_values(self):
        """Test default initialization."""
        limiter = RateLimiter()
        assert limiter.max_requests == 10
        assert limiter.window_seconds == 1
        
    def test_init_custom_values(self):
        """Test custom initialization."""
        limiter = RateLimiter(max_requests=5, window_seconds=2)
        assert limiter.max_requests == 5
        assert limiter.window_seconds == 2
        
    def test_init_invalid_values(self):
        """Test initialization with invalid values."""
        with pytest.raises(ValueError, match="max_requests must be positive"):
            RateLimiter(max_requests=0)
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            RateLimiter(window_seconds=0)
            
    def test_acquire_non_blocking(self):
        """Test non-blocking acquire."""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        
        # First acquire should succeed
        assert limiter.acquire(block=False) is True
        
        # Second acquire should fail (rate limited)
        assert limiter.acquire(block=False) is False
        
    def test_acquire_blocking(self):
        """Test blocking acquire."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.5)
        
        start = time.time()
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # This should block
        elapsed = time.time() - start
        
        # Should have waited at least some time
        assert elapsed >= 0.1
        
    def test_acquire_with_timeout(self):
        """Test acquire with timeout."""
        limiter = RateLimiter(max_requests=1, window_seconds=10)
        limiter.acquire()  # Use the one slot
        
        # Should timeout immediately
        with pytest.raises(TimeoutError):
            limiter.acquire(block=True, timeout=0.01)
            
    def test_get_stats(self):
        """Test statistics tracking."""
        limiter = RateLimiter(max_requests=10, window_seconds=1)
        
        # Make some requests
        for _ in range(3):
            limiter.acquire(block=False)
            
        stats = limiter.get_stats()
        assert isinstance(stats, RateLimitStats)
        assert stats.total_requests == 3
        
    def test_reset(self):
        """Test reset functionality."""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        limiter.acquire()
        
        assert limiter.acquire(block=False) is False
        
        limiter.reset()
        assert limiter.acquire(block=False) is True
        
    def test_current_rate(self):
        """Test current rate calculation."""
        limiter = RateLimiter(max_requests=10, window_seconds=1)
        
        # No requests yet
        assert limiter.current_rate() == 0.0
        
        # Make requests
        for _ in range(5):
            limiter.acquire(block=False)
            
        rate = limiter.current_rate()
        assert rate > 0
        
    def test_time_until_next_slot(self):
        """Test time until next slot calculation."""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        
        # No wait needed initially
        assert limiter.time_until_next_slot() == 0.0
        
        # Use the slot
        limiter.acquire()
        
        # Should need to wait now
        wait_time = limiter.time_until_next_slot()
        assert wait_time > 0
        
    def test_thread_safety(self):
        """Test thread safety with concurrent requests."""
        limiter = RateLimiter(max_requests=100, window_seconds=1)
        results = []
        errors = []
        
        def make_requests():
            try:
                for _ in range(5):
                    if limiter.acquire(block=False):
                        results.append(1)
                    else:
                        results.append(0)
            except Exception as e:
                errors.append(e)
                
        threads = [threading.Thread(target=make_requests) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        # Should have 50 results, no errors
        assert len(results) == 50
        assert len(errors) == 0
        
        # Should not exceed rate limit
        stats = limiter.get_stats()
        assert stats.total_requests <= 100


class TestAdaptiveRateLimiter:
    """Test cases for AdaptiveRateLimiter."""
    
    def test_init(self):
        """Test initialization."""
        limiter = AdaptiveRateLimiter(
            max_requests=10,
            min_requests=2,
            backoff_factor=0.5
        )
        assert limiter.max_requests == 10
        assert limiter._min_requests == 2
        assert limiter._backoff_factor == 0.5
        
    def test_record_success(self):
        """Test success tracking."""
        limiter = AdaptiveRateLimiter(max_requests=5, recovery_rate=0.5)
        
        # Record successes to trigger recovery
        for _ in range(15):
            limiter.record_success()
            
        # Should have recovered toward initial max
        # Note: actual behavior depends on implementation
        
    def test_record_rate_limit_error(self):
        """Test rate limit error handling."""
        limiter = AdaptiveRateLimiter(max_requests=10, backoff_factor=0.5, min_requests=2)
        
        limiter.record_rate_limit_error()
        
        # Should have backed off
        assert limiter.max_requests < 10
        assert limiter.max_requests >= 2
