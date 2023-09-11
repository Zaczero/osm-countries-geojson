import gzip
from decimal import Decimal

import anyio
import brotli
import orjson
from shapely.geometry import mapping
from tqdm import tqdm

from config import GEOJSON_DIR, GEOJSON_QUALITIES
from natural_earth import validate_countries
from osm_countries_gen import get_osm_countries


async def main():
    countries, data_timestamp = await get_osm_countries()

    await validate_countries(countries)

    for q in tqdm(GEOJSON_QUALITIES, desc='Writing GeoJSON'):
        q_str = f'{Decimal(str(q)):f}'.replace('.', '-')
        path = GEOJSON_DIR / f'osm-countries-{q_str}.geojson'

        features = []

        for country in countries:
            features.append({
                'type': 'Feature',
                'properties': {
                    'tags': country.tags,
                    'timestamp': data_timestamp,
                    'representative_point': mapping(country.representative_point),
                },
                'geometry': mapping(country.geometry[q]),
            })

        data = {
            'type': 'FeatureCollection',
            'name': path.stem,
            'crs': {
                'type': 'name',
                'properties': {
                    'name': 'urn:ogc:def:crs:OGC:1.3:CRS84',
                },
            },
            'features': features,
        }

        buffer = orjson.dumps(data)

        # uncompressed
        await path.write_bytes(buffer)

        # gzip compressed
        gz_path = path.with_suffix('.geojson.gz')
        await gz_path.write_bytes(gzip.compress(buffer, compresslevel=9))

        # brotli compressed
        br_path = path.with_suffix('.geojson.br')
        await br_path.write_bytes(brotli.compress(buffer, mode=brotli.MODE_TEXT, quality=11))


if __name__ == "__main__":
    anyio.run(main)
