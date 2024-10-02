from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from shapely import LinearRing, get_coordinates, linearrings, multipolygons, polygons
from shapely.geometry import MultiPolygon, Polygon


class _RingData(NamedTuple):
    geom_id: int
    poly_id: int
    coords: NDArray[np.complexfloating]


class _SplitRingData(NamedTuple):
    geom_id: int
    poly_id: int
    arcs: Sequence[NDArray[np.complexfloating]]


class Topology:
    __slots__ = ('_rings',)
    _rings: Collection[_SplitRingData]

    def __init__(self, geoms: Iterable[Polygon | MultiPolygon]):
        coords_data = _get_rings_data(geoms)
        endpoints = _find_endpoints(coords_data)
        self._rings = _split_into_arcs(coords_data, endpoints)

    def simplify(self, tolerance: float) -> list[Polygon | MultiPolygon]:
        polys, geoms_sizes = _reconstruct_polys(_simplify_arcs(self._rings, tolerance))
        return _reconstruct_geoms(polys, geoms_sizes)


def _get_rings_data(geoms: Iterable[Polygon | MultiPolygon]) -> list[_RingData]:
    rings_data: list[_RingData] = []
    poly_id = -1
    for geom_id, geom in enumerate(geoms):
        for poly_id, poly in enumerate(geom.geoms if isinstance(geom, MultiPolygon) else (geom,), start=poly_id + 1):  # noqa: B020
            for ring in (poly.exterior, *poly.interiors):
                coords2 = get_coordinates(ring)[:-1]  # skip last point
                coords1 = coords2[:, 0] + coords2[:, 1] * 1j
                rings_data.append(_RingData(geom_id, poly_id, coords1))
    return rings_data


def _find_endpoints(rings_data: Iterable[_RingData]) -> NDArray[np.complexfloating]:
    all_coords = np.hstack(tuple(c.coords for c in rings_data))
    unique_coords, counts = np.unique(all_coords, return_counts=True)  # unique_coords are sorted
    del all_coords
    mask = np.zeros_like(unique_coords, dtype=np.bool_)

    for ring in rings_data:
        coords = ring.coords
        unique_indices = np.searchsorted(unique_coords, coords)
        ring_counts = counts[unique_indices]
        changes = np.diff(ring_counts, append=ring_counts[0])
        mask[unique_indices[(changes < 0) | np.roll((changes > 0), 1)]] = True

    return unique_coords[mask]


def _split_into_arcs(rings_data: Iterable[_RingData], endpoints: NDArray[np.complexfloating]) -> list[_SplitRingData]:
    result: list[_SplitRingData] = []
    for ring in rings_data:
        coords = ring.coords
        nearby_endpoint_indices = np.searchsorted(endpoints, coords).clip(max=len(endpoints) - 1)
        split_indices = np.flatnonzero(coords == endpoints[nearby_endpoint_indices])
        match len(split_indices):
            case 0:  # case: no splits
                arcs_coords = (np.append(coords, coords[0]),)
            case 1:  # case: single split
                arcs_coords = (np.hstack((coords[split_indices[0] :], coords[: split_indices[0] + 1])),)
            case _:  # case: multiple splits
                arcs_coords = [
                    coords[start_idx:end_idx]
                    for start_idx, end_idx in zip(split_indices, np.roll(split_indices, -1) + 1, strict=True)
                ]
                arcs_coords[-1] = np.hstack((coords[split_indices[-1] :], coords[: split_indices[0] + 1]))
        result.append(_SplitRingData(ring.geom_id, ring.poly_id, arcs_coords))
    return result


def _simplify_arcs(rings_data: Iterable[_SplitRingData], tolerance: float) -> list[_SplitRingData]:
    result: list[_SplitRingData] = []
    for ring in rings_data:
        ring_tolerance = tolerance
        new_arcs: list[NDArray[np.complexfloating]] = []
        while True:
            # repeat until enough coords remain
            max_distance = 0
            new_coords_len = 0
            for arc in ring.arcs:
                new_arc, max_distance = _douglas_peucker(arc, ring_tolerance, max_distance)
                new_arcs.append(new_arc)
                if new_coords_len < 3:
                    new_coords_len += len(new_arc) - 1
            if new_coords_len >= 3 or max_distance == 0:
                break
            ring_tolerance = min(ring_tolerance, max_distance)
            new_arcs.clear()
        result.append(_SplitRingData(ring.geom_id, ring.poly_id, new_arcs))
    return result


def _douglas_peucker(
    coords: NDArray[np.complexfloating], tolerance: float, max_distance: float
) -> tuple[NDArray[np.complexfloating], float]:
    coords_len = len(coords)
    if coords_len <= 2:
        return coords, max_distance
    keep = np.zeros(coords_len, dtype=np.bool_)
    keep[0] = True
    keep[-1] = True
    stack: list[tuple[int | np.integer, int | np.integer]] = [(0, coords_len - 1)]

    while stack:
        start_idx, end_idx = stack.pop()
        start: np.complexfloating = coords[start_idx]
        end: np.complexfloating = coords[end_idx]
        u = coords[start_idx + 1 : end_idx] - start  # point vector

        if start == end:
            distances = np.abs(u)
        else:
            # calculate perpendicular distances
            segment = end - start
            segment_length = np.abs(segment)
            distances = np.abs(np.imag(np.conj(segment) * u)) / segment_length

        max_idx = np.argmax(distances)
        max_distance_ = distances[max_idx]
        if max_distance_ >= tolerance:
            idx = start_idx + max_idx + 1
            keep[idx] = True
            if idx - start_idx > 1:
                stack.append((start_idx, idx))
            if end_idx - idx > 1:
                stack.append((idx, end_idx))
        else:
            max_distance = max(max_distance, max_distance_)

    return coords[keep], max_distance


def _reconstruct_polys(rings_data: Iterable[_SplitRingData]) -> tuple[Sequence[Polygon], list[int]]:
    rings_coords_stack: list[NDArray[np.complexfloating]] = []
    rings_coords_sizes: list[int] = []
    polys_sizes: list[int] = []
    geoms_sizes: list[int] = []
    last_poly_id = -1
    last_geom_id = -1
    for ring in rings_data:
        coords = np.hstack(tuple(c[:-1] for c in ring.arcs))
        coords_len = len(coords)
        rings_coords_stack.append(coords)
        rings_coords_sizes.append(coords_len)

        if last_poly_id != (poly_id := ring.poly_id):
            last_poly_id = poly_id
            polys_sizes.append(1)

            if last_geom_id != (geom_id := ring.geom_id):
                last_geom_id = geom_id
                geoms_sizes.append(1)
            else:
                geoms_sizes[-1] += 1
        else:
            polys_sizes[-1] += 1

    rings_indices = np.repeat(np.arange(len(rings_coords_sizes), dtype=np.uint32), rings_coords_sizes)
    del rings_coords_sizes
    rings_coords = np.hstack(rings_coords_stack)
    del rings_coords_stack
    rings_coords = np.dstack((rings_coords.real, rings_coords.imag))[0]
    rings: Sequence[LinearRing] = linearrings(rings_coords, indices=rings_indices)  # pyright: ignore[reportAssignmentType]
    del rings_coords, rings_indices
    polys_indices = np.repeat(np.arange(len(polys_sizes), dtype=np.uint32), polys_sizes)
    polys: Sequence[Polygon] = polygons(rings, indices=polys_indices)  # pyright: ignore[reportAssignmentType]
    return polys, geoms_sizes


def _reconstruct_geoms(polys: Sequence[Polygon], geoms_sizes: Sequence[int]) -> list[Polygon | MultiPolygon]:
    geoms_len = len(geoms_sizes)
    geoms_end_indices = np.cumsum(geoms_sizes)
    geoms_start_indices = np.roll(geoms_end_indices, 1)
    geoms_start_indices[0] = 0
    result: list[Polygon | MultiPolygon] = [None] * geoms_len  # pyright: ignore[reportAssignmentType]
    for i, start_idx, end_idx in zip(range(geoms_len), geoms_start_indices, geoms_end_indices, strict=True):
        if end_idx - start_idx == 1:  # case: Polygon
            result[i] = polys[start_idx]
        else:  # case: MultiPolygon
            result[i] = multipolygons(polys[start_idx:end_idx])
    return result
