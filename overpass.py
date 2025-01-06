from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from config import OVERPASS_API_INTERPRETER
from utils import HTTP, retry_exponential


@retry_exponential(timedelta(minutes=30))
async def query_overpass(query: str, *, timeout: int, must_return: bool = True) -> tuple[Sequence[dict], float]:
    join = '' if query.startswith('[') else ';'
    query = f'[out:json][timeout:{timeout}]{join}{query}'

    r = await HTTP.post(OVERPASS_API_INTERPRETER, data={'data': query}, timeout=timeout * 2)
    r.raise_for_status()

    data = r.json()
    data_timestamp = (
        datetime.strptime(
            data['osm3s']['timestamp_osm_base'],
            '%Y-%m-%dT%H:%M:%SZ',
        )
        .replace(tzinfo=UTC)
        .timestamp()
    )

    if must_return and not data['elements']:
        raise Exception('No elements returned')

    return data['elements'], data_timestamp
