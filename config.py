from anyio import Path

NAME = 'osm-countries-geojson'
VERSION = '1.2.0'
WEBSITE = 'https://github.com/Zaczero/osm-countries-geojson'
USER_AGENT = f'{NAME}/{VERSION} (+{WEBSITE})'

OVERPASS_API_URL = 'https://overpass.monicz.dev/api/interpreter'
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
