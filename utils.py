import asyncio
import functools
import sys
import time
import traceback
from collections.abc import Awaitable, Callable, Iterator, Sequence
from datetime import timedelta

from httpx import AsyncClient, HTTPStatusError, Timeout, TransportError
from httpx_secure import httpx_ssrf_protection

from config import USER_AGENT

HTTP = httpx_ssrf_protection(
    AsyncClient(
        headers={'User-Agent': USER_AGENT},
        timeout=Timeout(60, connect=15),
        follow_redirects=True,
    )
)


def progress[T](items: Sequence[T], *, desc: str) -> Iterator[T]:
    total = len(items)
    last = time.monotonic()
    print(f'{desc}: 0/{total}', file=sys.stderr, flush=True)
    for index, item in enumerate(items, 1):
        yield item
        now = time.monotonic()
        if index == total or now - last >= 1:
            print(f'{desc}: {index}/{total}', file=sys.stderr, flush=True)
            last = now


def retry_exponential[**P, T](
    timeout: timedelta | None,
    *,
    start: float = 1,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    timeout_seconds = timeout.total_seconds() if timeout else float('inf')

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            ts = time.perf_counter()
            sleep = start

            while True:
                try:
                    return await func(*args, **kwargs)
                except (TransportError, HTTPStatusError) as error:
                    if isinstance(error, HTTPStatusError) and error.response.status_code not in (
                        408,
                        429,
                        500,
                        502,
                        503,
                        504,
                    ):
                        raise
                    print(f'[⛔] {func.__name__} failed')
                    traceback.print_exc()
                    if (time.perf_counter() + sleep) - ts > timeout_seconds:
                        raise
                    await asyncio.sleep(sleep)
                    sleep = min(sleep * 2, 1800)  # max 30 minutes

        return wrapper

    return decorator
