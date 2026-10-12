import gzip
import sys
from compression import zstd
from functools import partial
from pathlib import Path

import brotli
import sentry_sdk
from zopfli.gzip import compress as zopfli_compress

from config import DOWNLOAD_NAMES, GEOJSON_DIR, GEOJSON_QUALITIES, geojson_name


def compress_geojson(directory: Path = GEOJSON_DIR) -> None:
    for name in DOWNLOAD_NAMES:
        if not name.endswith('.geojson'):
            (directory / name).unlink(missing_ok=True)
    for quality in GEOJSON_QUALITIES:
        source = directory / geojson_name(quality)
        data = source.read_bytes()
        # Match the CLI's window: usable history is 2**lgwin - 16 bytes.
        window = min(24, max(10, (len(data) + 15).bit_length()))
        codecs = (
            ('.gz', zopfli_compress, gzip.decompress),
            ('.br', partial(brotli.compress, lgwin=window), brotli.decompress),
            (
                '.zst',
                partial(
                    zstd.compress,
                    options={
                        zstd.CompressionParameter.compression_level: 22,
                        zstd.CompressionParameter.checksum_flag: 1,
                    },
                ),
                zstd.decompress,
            ),
        )
        for suffix, encode, decode in codecs:
            output = source.with_suffix(source.suffix + suffix)
            print(f'Compressing {output.name}', file=sys.stderr, flush=True)
            with sentry_sdk.start_span(op='compression', name=output.name) as span:
                output.write_bytes(encode(data))
                if decode(output.read_bytes()) != data:
                    raise RuntimeError(f'Compression verification failed: {output.name}')
                span.set_data('input.size', len(data))
                span.set_data('output.size', output.stat().st_size)
