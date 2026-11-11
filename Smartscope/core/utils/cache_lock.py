"""Cross-worker locks backed by the Django cache (Redis).

Unlike lock files, these expire after `ttl` seconds, so a worker killed mid-task
(OOM, container restart) can't leave a grid locked forever.
"""
import time
import logging
from contextlib import contextmanager
from typing import Optional
from uuid import uuid4

from django.core.cache import cache

logger = logging.getLogger(__name__)


class CacheLockTimeout(Exception):
    pass


def acquire_cache_lock(key: str, ttl: int, wait: float = 0, poll: float = 2.0) -> Optional[str]:
    """Try to take the lock, polling for up to `wait` seconds. Returns an owner token, or None."""
    token = uuid4().hex
    deadline = time.monotonic() + wait
    while True:
        if cache.add(key, token, timeout=ttl):
            return token
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def release_cache_lock(key: str, token: str) -> None:
    """Release only if we still own it (it may have expired and been taken by someone else)."""
    if cache.get(key) == token:
        cache.delete(key)


@contextmanager
def cache_lock(key: str, ttl: int, wait: float = 0, poll: float = 2.0):
    token = acquire_cache_lock(key, ttl, wait=wait, poll=poll)
    if token is None:
        raise CacheLockTimeout(f'Could not acquire lock {key} within {wait}s')
    try:
        yield token
    finally:
        release_cache_lock(key, token)
