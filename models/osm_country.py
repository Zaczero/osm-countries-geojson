from typing import NamedTuple


class OSMCountry(NamedTuple):
    tags: dict[str, str]
    geometry: dict[float, dict]
    representative_point: dict
