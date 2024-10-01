from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from shapely import get_coordinates
from shapely.geometry import MultiPolygon, Polygon


class Topology(NamedTuple):
    arcs: list[NDArray[np.float64]]
    geoms: list[list[list[int]]]


def topology(geoms: Sequence[Polygon | MultiPolygon]) -> Topology:
    coords, index = get_coordinates(geoms, return_index=True)

    # create a set of endpoints
    coords_unique, counts = np.unique(coords, axis=0, return_counts=True)
    endpoints = frozenset(tuple(c) for c in coords_unique[counts > 1])
