"""Token bucket rate limiter for API requests.

This module provides a thread-safe token bucket rate limiter that enforces
maximum request rates per time window. Designed for SEC EDGAR API compliance
(10 requests per second maximum).
"""

import time
import logging
from collections import deque
from threading import Lock
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStats:
    """Statistics for rate limiter performance monitoring."""
    total_requests: int = 0
    delayed_requests: int = 0
    total_delay_seconds: float = 0.0
    current_bucket_size: int = 0
    last_request_time: Optional[float] = field(default=None)


class RateLimiter:
    """Token bucket rate limiter for controlling API request rates.
    
    This implementation uses a token bucket algorithm that allows bursts
    up to the max_requests limit, then enforces the rate limit. It's
    thread-safe and suitable for concurrent API clients.
    
    Args:
        max_requests: Maximum number of requests allowed per window.
        window_seconds: Time window in seconds for the rate limit.
        
    Example:
        >>> limiter = RateLimiter(max_requests=10, window_seconds=1)
        >>> limiter.acquire()  # Blocks if rate limit would be exceeded
        >>> make_api_call()
        
    Attributes:
        max_requests: The configured maximum requests per window.
        window_seconds: The configured time window in seconds.
    """
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 1):
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
            
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = deque()
        self._lock = Lock()
        self._stats = RateLimitStats()
        
        logger.debug(
            f"RateLimiter initialized: {max_requests} requests per {window_seconds}s"
        )
    
    def acquire(self, block: bool = True, timeout: Optional[float] = None) -> bool:
        """Acquire permission to make a request.
        
        Args:
            block: If True, block until a slot is available. If False,
                   return immediately with success/failure status.
            timeout: Maximum time to wait in seconds. Only used if block=True.
                    None means wait indefinitely.
                    
        Returns:
            True if a request slot was acquired, False if non-blocking and
            the rate limit would be exceeded.
            
        Raises:
            TimeoutError: If timeout is reached while waiting for a slot.
        """
        start_time = time.time()
        
        with self._lock:
            while True:
                now = time.time()
                
                # Remove expired timestamps outside the window
                cutoff = now - self.window_seconds
                while self._requests and self._requests[0] < cutoff:
                    self._requests.popleft()
                
                # Check if we can proceed
                if len(self._requests) < self.max_requests:
                    self._requests.append(now)
                    self._stats.total_requests += 1
                    self._stats.last_request_time = now
                    self._stats.current_bucket_size = len(self._requests)
                    
                    logger.debug(
                        f"Rate limit slot acquired. Bucket: {len(self._requests)}/{self.max_requests}"
                    )
                    return True
                
                # Rate limit would be exceeded
                if not block:
                    logger.debug("Rate limit would be exceeded (non-blocking mode)")
                    return False
                
                # Calculate wait time
                sleep_time = self._requests[0] - cutoff
                
                # Check timeout
                if timeout is not None:
                    elapsed = now - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Timeout waiting for rate limit slot after {timeout}s"
                        )
                    sleep_time = min(sleep_time, remaining)
                
                self._stats.delayed_requests += 1
                
                # Release lock while sleeping to allow other threads
                self._lock.release()
                try:
                    logger.debug(f"Rate limit hit, sleeping for {sleep_time:.3f}s")
                    time.sleep(max(0, sleep_time))
                    self._stats.total_delay_seconds += sleep_time
                finally:
                    self._lock.acquire()
                
                # Loop continues to recheck with lock held
    
    def get_stats(self) -> RateLimitStats:
        """Get current rate limiter statistics.
        
        Returns:
            RateLimitStats object with current metrics.
        """
        with self._lock:
            # Update current bucket size
            now = time.time()
            cutoff = now - self.window_seconds
            while self._requests and self._requests[0] < cutoff:
                self._requests.popleft()
            
            self._stats.current_bucket_size = len(self._requests)
            return RateLimitStats(
                total_requests=self._stats.total_requests,
                delayed_requests=self._stats.delayed_requests,
                total_delay_seconds=self._stats.total_delay_seconds,
                current_bucket_size=self._stats.current_bucket_size,
                last_request_time=self._stats.last_request_time
            )
    
    def reset(self):
        """Reset the rate limiter state.
        
        Clears all tracked requests and statistics. Useful for testing
        or when switching to a different API context.
        """
        with self._lock:
            self._requests.clear()
            self._stats = RateLimitStats()
            logger.debug("RateLimiter reset")
    
    def current_rate(self) -> float:
        """Calculate current request rate over the window.
        
        Returns:
            Requests per second over the current window.
        """
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            
            # Count requests in current window
            count = sum(1 for t in self._requests if t >= cutoff)
            return count / self.window_seconds if self.window_seconds > 0 else 0.0
    
    def time_until_next_slot(self) -> float:
        """Estimate time until the next request slot will be available.
        
        Returns:
            Seconds until a slot is available. 0.0 if a slot is available now.
        """
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            
            # Clean expired
            while self._requests and self._requests[0] < cutoff:
                self._requests.popleft()
            
            if len(self._requests) < self.max_requests:
                return 0.0
            
            # Time until oldest request expires
            return max(0.0, self._requests[0] - cutoff)


class AdaptiveRateLimiter(RateLimiter):
    """Rate limiter that adapts to server responses.
    
    Extends the base RateLimiter to automatically reduce rate when
    receiving 429 (Too Many Requests) or 503 (Service Unavailable)
    responses, then gradually restores rate on success.
    
    Args:
        max_requests: Initial maximum requests per window.
        window_seconds: Time window in seconds.
        min_requests: Minimum requests per window (floor for backoff).
        backoff_factor: Factor to multiply by on rate limit error.
        recovery_rate: How quickly to restore rate after success (0-1).
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 1,
        min_requests: int = 1,
        backoff_factor: float = 0.5,
        recovery_rate: float = 0.1
    ):
        super().__init__(max_requests, window_seconds)
        self._initial_max = max_requests
        self._min_requests = min_requests
        self._backoff_factor = backoff_factor
        self._recovery_rate = recovery_rate
        self._consecutive_successes = 0
    
    def record_success(self):
        """Record a successful API response.
        
        Gradually restores rate limit after consecutive successes.
        """
        self._consecutive_successes += 1
        
        # Recovery every N successes
        if self._consecutive_successes >= 10:
            with self._lock:
                current = self.max_requests
                new_limit = min(
                    self._initial_max,
                    int(current + (self._initial_max - current) * self._recovery_rate) + 1
                )
                if new_limit != current:
                    self.max_requests = new_limit
                    logger.info(f"Rate limit recovered to {new_limit} req/s")
            self._consecutive_successes = 0
    
    def record_rate_limit_error(self):
        """Record a rate limit (429) or server overload (503) response.
        
        Immediately reduces the rate limit and resets success counter.
        """
        self._consecutive_successes = 0
        
        with self._lock:
            current = self.max_requests
            new_limit = max(
                self._min_requests,
                int(current * self._backoff_factor)
            )
            if new_limit < current:
                self.max_requests = new_limit
                logger.warning(
                    f"Rate limit hit, backing off to {new_limit} req/s"
                )
                # Clear request history to allow immediate retry at lower rate
                self._requests.clear()
