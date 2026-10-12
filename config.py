import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path

NAME = 'osm-countries-geojson'
REVISION = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()  # noqa: S607 -- Git is provided by the environment.
VERSION = 'git#' + REVISION[:7]
WEBSITE = 'https://github.com/Zaczero/osm-countries-geojson'
USER_AGENT = f'{NAME}/{VERSION} (+{WEBSITE})'
PUBLICATION: dict[str, str] = json.loads(Path(__file__).with_name('publication.json').read_text())

OVERPASS_API_INTERPRETER = os.getenv('OVERPASS_API_INTERPRETER', 'https://overpass-api.de/api/interpreter')
COUNTRIES_GEOJSON_URL = (
    'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_sovereignty.geojson'
)

GEOJSON_DIR = Path('geojson')

GEOJSON_QUALITIES = (
    0.00001,
    0.0001,
    0.001,
    0.01,
    0.1,
)

BEST_GEOJSON_QUALITY = min(GEOJSON_QUALITIES)


def geojson_name(quality: float) -> str:
    value = format(Decimal(str(quality)), 'f').replace('.', '-')
    return f'osm-countries-{value}.geojson'


DOWNLOAD_NAMES = tuple(
    geojson_name(quality) + suffix for quality in GEOJSON_QUALITIES for suffix in ('', '.br', '.gz', '.zst')
)
