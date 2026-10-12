import asyncio
from datetime import timedelta

import pytest
from httpx import HTTPStatusError, Request, Response

from utils import retry_exponential


def test_programming_error_is_not_retried():
    attempts = 0

    @retry_exponential(timedelta(seconds=10))
    async def operation():
        nonlocal attempts
        attempts += 1
        raise TypeError('Incorrect application argument')

    with pytest.raises(TypeError):
        asyncio.run(operation())
    assert attempts == 1


@pytest.mark.parametrize('status', [401, 403, 404])
def test_permanent_http_failure_is_not_retried(status):
    attempts = 0

    @retry_exponential(timedelta(seconds=10))
    async def operation():
        nonlocal attempts
        attempts += 1
        Response(status, request=Request('GET', 'https://example.invalid/')).raise_for_status()

    with pytest.raises(HTTPStatusError):
        asyncio.run(operation())
    assert attempts == 1


def test_transient_http_failure_can_recover():
    attempts = 0

    @retry_exponential(timedelta(seconds=10), start=0)
    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            Response(503, request=Request('GET', 'https://example.invalid/')).raise_for_status()
        return 'complete'

    assert asyncio.run(operation()) == 'complete'
    assert attempts == 2


def test_exhausted_transient_failure_propagates():
    @retry_exponential(timedelta(seconds=-1))
    async def operation():
        Response(503, request=Request('GET', 'https://example.invalid/')).raise_for_status()

    with pytest.raises(HTTPStatusError):
        asyncio.run(operation())
