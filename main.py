import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import sentry_sdk
from shapely.geometry import mapping

from config import GEOJSON_DIR, GEOJSON_QUALITIES, geojson_name
from monitoring import init_sentry
from natural_earth import validate_countries
from osm_countries_gen import OSMCountry, get_osm_countries
from utils import progress


def write_geojson(path: Path, countries: Sequence[OSMCountry], data_timestamp: float, quality: float) -> None:
    header = {
        'type': 'FeatureCollection',
        'name': path.stem,
        'crs': {
            'type': 'name',
            'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'},
        },
    }
    with path.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(header, ensure_ascii=False)[:-1])
        stream.write(', "features": [')
        for index, country in enumerate(countries):
            if index:
                stream.write(', ')
            feature = {
                'type': 'Feature',
                'properties': {
                    'tags': country.tags,
                    'timestamp': data_timestamp,
                    'representative_point': country.representative_point,
                },
                'geometry': mapping(country.geometry[quality]),
            }
            stream.write(json.dumps(feature, ensure_ascii=False, check_circular=False, allow_nan=False))
        stream.write(']}')


async def main():
    # ensure output directory exists
    GEOJSON_DIR.mkdir(exist_ok=True)

    with sentry_sdk.start_span(op='geo.generate', name='Build country geometries') as span:
        countries, data_timestamp = await get_osm_countries()
        span.set_data('countries', len(countries))
        span.set_data('data_timestamp', data_timestamp)

    with sentry_sdk.start_span(op='geo.validate', name='Validate country coverage'):
        await validate_countries(countries)

    for q in progress(GEOJSON_QUALITIES, desc='Writing GeoJSON'):
        path = GEOJSON_DIR / geojson_name(q)

        with sentry_sdk.start_span(op='file.write', name=path.name) as span:
            write_geojson(path, countries, data_timestamp, q)
            span.set_data('file.size', path.stat().st_size)


if __name__ == '__main__':
    init_sentry()
    with sentry_sdk.start_transaction(op='task', name='generate-raw-geojson'):
        asyncio.run(main())
