from decimal import Decimal

import msgspec
import uvloop
from shapely.geometry import mapping
from tqdm import tqdm

from config import GEOJSON_DIR, GEOJSON_QUALITIES
from natural_earth import validate_countries
from osm_countries_gen import get_osm_countries


async def main():
    # ensure output directory exists
    GEOJSON_DIR.mkdir(exist_ok=True)

    countries, data_timestamp = await get_osm_countries()

    await validate_countries(countries)

    for q in tqdm(GEOJSON_QUALITIES, desc='Writing GeoJSON'):
        q_str = f'{Decimal(str(q)):f}'.replace('.', '-')
        path = GEOJSON_DIR / f'osm-countries-{q_str}.geojson'

        features = tuple(
            {
                'type': 'Feature',
                'properties': {
                    'tags': country.tags,
                    'timestamp': data_timestamp,
                    'representative_point': country.representative_point,
                },
                'geometry': mapping(country.geometry[q]),
            }
            for country in countries
        )

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

        buffer = msgspec.json.encode(data)
        path.write_bytes(buffer)


if __name__ == '__main__':
    uvloop.run(main())
