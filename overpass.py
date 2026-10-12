import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from config import OVERPASS_API_INTERPRETER
from utils import HTTP, retry_exponential


@retry_exponential(timedelta(minutes=30))
async def query_overpass(
    query: str, *, http_timeout: int, must_return: bool = True
) -> tuple[Sequence[dict[str, Any]], float]:
    join = '' if query.startswith('[') else ';'
    query = f'[out:json][timeout:{http_timeout}]{join}{query}'

    r = await HTTP.post(OVERPASS_API_INTERPRETER, data={'data': query}, timeout=http_timeout * 2)
    r.raise_for_status()

    return parse_response(r.content, must_return=must_return)


def parse_response(content: bytes, *, must_return: bool = True) -> tuple[Sequence[dict[str, Any]], float]:
    data = json.loads(content)
    if remark := data.get('remark'):
        raise RuntimeError(f'Overpass returned an incomplete result: {remark}')
    data_timestamp = datetime.fromisoformat(data['osm3s']['timestamp_osm_base'])
    if data_timestamp.tzinfo is None:
        raise ValueError('Overpass timestamp has no timezone')

    if must_return and not data['elements']:
        raise Exception('No elements returned')

    return data['elements'], data_timestamp.timestamp()
