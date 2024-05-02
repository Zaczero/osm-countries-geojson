import gzip
import pathlib
from concurrent.futures import Future, ProcessPoolExecutor
from decimal import Decimal

import anyio
import brotli
import msgspec
from anyio import Path
from shapely.geometry import mapping
from tqdm import tqdm
from zstandard import ZstdCompressor

from config import GEOJSON_DIR, GEOJSON_QUALITIES
from natural_earth import validate_countries
from osm_countries_gen import get_osm_countries


def compress_brotli(path: Path, data: bytes) -> None:
    out_path = path.with_suffix('.geojson.br')
    buffer = brotli.compress(data, mode=brotli.MODE_TEXT, quality=11)
    pathlib.Path(out_path).write_bytes(buffer)


def compress_gzip(path: Path, data: bytes) -> None:
    out_path = path.with_suffix('.geojson.gz')
    buffer = gzip.compress(data, compresslevel=9)
    pathlib.Path(out_path).write_bytes(buffer)


def compress_zstd(path: Path, data: bytes) -> None:
    out_path = path.with_suffix('.geojson.zst')
    buffer = ZstdCompressor(level=22).compress(data)
    pathlib.Path(out_path).write_bytes(buffer)


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

            buffer = msgspec.json.encode(data)

            # uncompressed
            await path.write_bytes(buffer)

            futures.append(pool.submit(compress_brotli, path, buffer))
            futures.append(pool.submit(compress_gzip, path, buffer))
            futures.append(pool.submit(compress_zstd, path, buffer))

        print('Compressing GeoJSON files...')
        for future in futures:
            future.result()


if __name__ == '__main__':
    anyio.run(main)
