
from typing import NamedTuple

from shapely.geometry import MultiPolygon, Point, Polygon


class OSMCountry(NamedTuple):
    tags: dict[str, str]
    geometry: dict[float, Polygon | MultiPolygon]
    representative_point: Point
