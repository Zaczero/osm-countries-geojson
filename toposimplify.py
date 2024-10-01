from collections.abc import Collection, Iterable
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from shapely import box, get_coordinates
from shapely.geometry import MultiPolygon, Polygon


class _CoordsData(NamedTuple):
    geom_i: int
    poly_i: int
    ring_i: int
    coords: NDArray[np.complexfloating]


class _ArcData(NamedTuple):
    geom_i: int
    poly_i: int
    ring_i: int
    coords: Collection[NDArray[np.complexfloating]]


class Topology(NamedTuple):
    arcs: Collection[_ArcData]


def topology(geoms: Iterable[Polygon | MultiPolygon]) -> Topology:
    coords_data = _get_coords_data(geoms)
    endpoints = _find_endpoints(coords_data)
    arcs = _split_into_arcs(coords_data, endpoints)
    return Topology(arcs=arcs)


def _get_coords_data(geoms: Iterable[Polygon | MultiPolygon]) -> list[_CoordsData]:
    coords_data: list[_CoordsData] = []
    for geom_i, geom in enumerate(geoms):
        for poly_i, poly in enumerate(geom.geoms if isinstance(geom, MultiPolygon) else (geom,)):
            for ring_i, ring in enumerate((poly.exterior, *poly.interiors)):
                coords2 = get_coordinates(ring)[:-1]  # skip last point
                coords1 = coords2[:, 0] + coords2[:, 1] * 1j
                coords_data.append(_CoordsData(geom_i, poly_i, ring_i, coords1))
    return coords_data


def _find_endpoints(coords_data: Iterable[_CoordsData]) -> NDArray[np.complexfloating]:
    all_coords = np.hstack(tuple(c.coords for c in coords_data))
    all_coords_unique, counts = np.unique(all_coords, return_counts=True)
    endpoints = all_coords_unique[counts > 1]
    endpoints.sort()
    return endpoints


def _split_into_arcs(coords_data: Iterable[_CoordsData], endpoints: NDArray[np.complexfloating]) -> list[_ArcData]:
    arc_data: list[_ArcData] = []
    for data in coords_data:
        coords = data.coords
        nearby_endpoint_indices = np.searchsorted(endpoints, coords).clip(max=len(endpoints) - 1)
        split_indices = np.flatnonzero(coords == endpoints[nearby_endpoint_indices])
        if split_indices.size == 0:  # case: no splits
            arcs_coords = (np.append(coords, coords[0]),)
        elif split_indices.size == 1:  # case: single split
            arcs_coords = (np.hstack((coords[split_indices[0] :], coords[: split_indices[0] + 1])),)
        else:  # case: multiple splits
            arcs_coords = [
                coords[start_idx:end_idx]
                for start_idx, end_idx in zip(split_indices, split_indices[1:] + 1, strict=False)
            ]
            arcs_coords.append(np.hstack((coords[split_indices[-1] :], coords[: split_indices[0] + 1])))
        arc_data.append(_ArcData(data.geom_i, data.poly_i, data.ring_i, arcs_coords))
    return arc_data


topology((box(0, 0, 1, 1), box(1, 0, 2, 1)))
