import asyncio
import functools
import time
import traceback
from datetime import timedelta

import httpx

from config import USER_AGENT


def retry_exponential(timeout: timedelta | None, *, start: float = 1):
    timeout_seconds = timeout.total_seconds() if timeout else float('inf')

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            ts = time.perf_counter()
            sleep = start

            while True:
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    print(f'[⛔] {func.__name__} failed')
                    traceback.print_exc()
                    if (time.perf_counter() + sleep) - ts > timeout_seconds:
                        raise
                    await asyncio.sleep(sleep)
                    sleep = min(sleep * 2, 1800)  # max 30 minutes

        return wrapper

    return decorator


def get_http_client(base_url: str = '') -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers={'User-Agent': USER_AGENT},
        timeout=httpx.Timeout(60, connect=15),
        follow_redirects=True,
    )
