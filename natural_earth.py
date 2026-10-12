from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from shapely import unary_union
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from config import BEST_GEOJSON_QUALITY, COUNTRIES_GEOJSON_URL
from osm_countries_gen import OSMCountry
from utils import HTTP, progress, retry_exponential


@retry_exponential(timedelta(minutes=30))
async def _get_countries() -> Sequence[dict[str, Any]]:
    r = await HTTP.get(COUNTRIES_GEOJSON_URL)
    r.raise_for_status()
    return r.json()['features']


async def validate_countries(countries: Sequence[OSMCountry]) -> None:
    ne_countries = await _get_countries()
    ne_countries = tuple(
        c
        for c in ne_countries
        if not any(
            n in c['properties']['NAME']
            for n in (
                # ignore some entries
                'Antarctica',
                'Sahara',
            )
        )
    )

    geometry_union: BaseGeometry = unary_union([c.geometry[BEST_GEOJSON_QUALITY] for c in countries])

    # validate country geometries by checking if the representative point is inside the geometry
    for ne_country in progress(ne_countries, desc='Validating'):
        ne_geom = shape(ne_country['geometry'])
        ne_point = ne_geom.representative_point()

        if not geometry_union.contains(ne_point):
            raise ValueError(f'Country geometry not found: {ne_country["properties"]["NAME"]!r}')
