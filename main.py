import gzip
import pathlib
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from decimal import Decimal

import anyio
import brotli
import orjson
from anyio import Path
from shapely.geometry import mapping
from tqdm import tqdm

from config import GEOJSON_DIR, GEOJSON_QUALITIES
from natural_earth import validate_countries
from osm_countries_gen import get_osm_countries


def compress_and_write(path: Path, data: bytes, func: Callable[..., bytes], *args, **kwargs) -> None:
    buffer = func(data, *args, **kwargs)
    pathlib.Path(path).write_bytes(buffer)


async def main():
    # ensure output directory exists
    await GEOJSON_DIR.mkdir(exist_ok=True)

    countries, data_timestamp = await get_osm_countries()

    await validate_countries(countries)

    with ProcessPoolExecutor() as pool:
        futures: list[Future] = []

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

            buffer = orjson.dumps(data)

            # uncompressed
            await path.write_bytes(buffer)

            # gzip compressed
            gz_path = path.with_suffix('.geojson.gz')
            futures.append(
                pool.submit(
                    compress_and_write,
                    gz_path,
                    buffer,
                    gzip.compress,
                    compresslevel=9,
                )
            )

            # brotli compressed
            br_path = path.with_suffix('.geojson.br')
            futures.append(
                pool.submit(
                    compress_and_write,
                    br_path,
                    buffer,
                    brotli.compress,
                    mode=brotli.MODE_TEXT,
                    quality=11,
                )
            )

        for future in tqdm(futures, desc='Compressing GeoJSON'):
            future.result()


if __name__ == '__main__':
    anyio.run(main)
