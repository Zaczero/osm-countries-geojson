import asyncio
import functools
import time
import traceback
from datetime import timedelta

from httpx import AsyncClient, Timeout
from httpx_secure import httpx_ssrf_protection

from config import USER_AGENT

HTTP = httpx_ssrf_protection(
    AsyncClient(
        headers={'User-Agent': USER_AGENT},
        timeout=Timeout(60, connect=15),
        follow_redirects=True,
    )
)


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
