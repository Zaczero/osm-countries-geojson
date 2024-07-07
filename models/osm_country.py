from typing import NamedTuple

from shapely.ops import BaseGeometry


class OSMCountry(NamedTuple):
    tags: dict[str, str]
    geometry: dict[float, BaseGeometry]
    representative_point: dict
