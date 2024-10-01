from collections import defaultdict
from collections.abc import Sequence
from itertools import chain, cycle, islice, pairwise
from typing import NamedTuple

import networkx as nx
import numpy as np
from shapely import Polygon
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import orient, unary_union
from tqdm import tqdm

from config import BEST_GEOJSON_QUALITY, GEOJSON_QUALITIES
from overpass import query_overpass


class OSMCountry(NamedTuple):
    tags: dict[str, str]
    geometry: dict[float, BaseGeometry]
    representative_point: dict


_QUERY = 'rel[boundary~"^(administrative|disputed)$"][admin_level=2]["ISO3166-1"][name];out geom qt;'


def _connect_segments(segments: Sequence[tuple[tuple]]) -> Sequence[Sequence[tuple]]:
    # count occurrences of each node
    node_count = defaultdict(int)
    for node in chain.from_iterable(segments):
        node_count[node] += 1

    # validate that all segments are closed (i.e., start and end at intersections)
    for s in segments:
        node_id_start = s[0]
        node_id_end = s[-1]
        if node_count[node_id_start] < 2 or node_count[node_id_end] < 2:
            raise ValueError(f'Segments must be closed (node/{node_id_start}, node/{node_id_end})')

    # node = intersection, node_count > 1
    # edge = segment between intersections
    graph = nx.DiGraph()

    # build the graph
    for segment in segments:
        subsegment_start = None
        subsegment = []
        for node in segment:
            # intersection node
            if node_count[node] > 1:
                if subsegment_start:
                    if len(subsegment) == 0:
                        graph.add_edge(subsegment_start, node)
                        graph.add_edge(node, subsegment_start)
                    elif len(subsegment) == 1:
                        first = subsegment[0]
                        graph.add_edge(subsegment_start, first)
                        graph.add_edge(first, node)
                        graph.add_edge(node, first)
                        graph.add_edge(first, subsegment_start)
                    else:
                        first = subsegment[0]
                        last = subsegment[-1]
                        graph.add_edge(subsegment_start, first)
                        graph.add_edge(first, last, subsegment=subsegment)
                        graph.add_edge(last, node)
                        graph.add_edge(node, last)
                        graph.add_edge(last, first, subsegment=subsegment[::-1])
                        graph.add_edge(first, subsegment_start)
                subsegment = []
                subsegment_start = node
            # normal node
            elif subsegment_start:
                subsegment.append(node)

    # set to store connected segments (closed loops)
    connected = set()

    # function to normalize a closed loop
    def connected_normalize(segment: list) -> tuple:
        min_idx = np.argmin(segment, axis=0)[0]

        # normalize starting point
        aligned = tuple(
            chain(
                islice(segment, min_idx, len(segment) - 1),
                islice(segment, min_idx + 1),
            )
        )

        # normalize orientation
        if segment[-1] < segment[1]:
            aligned = aligned[::-1]

        return aligned

    for c in nx.simple_cycles(graph):
        c = tuple(islice(cycle(c), len(c) + 1))  # close the cycle

        merged_unordered: list[list] = []

        for u, v in pairwise(c):
            if subsegment := graph[u][v].get('subsegment'):
                merged_unordered.append(subsegment)
            else:
                merged_unordered.append([u, v])

        if len(merged_unordered) < 2:
            # this realistically will mean broken data: a single node, a small loop, etc.
            raise Exception(f'Single-segment cycle ({c!r})')

        first = merged_unordered[0]
        second = merged_unordered[1]

        # proper orientation of the first segment
        if first[0] in (second[0], second[-1]):  # noqa: SIM108
            merged = first[::-1]
        else:
            merged = first

        for segment in merged_unordered[1:]:
            if merged[-1] == segment[0]:
                merged.extend(islice(segment, 1, None))
            elif merged[-1] == segment[-1]:
                merged.extend(islice(reversed(segment), 1, None))
            else:
                print('⚠️ Invalid cycle')
                break
        else:
            if len(merged) >= 4 and merged[1] != merged[-2]:
                connected.add(connected_normalize(merged))

    return tuple(connected)


async def get_osm_countries() -> tuple[Sequence[OSMCountry], float]:
    print('Querying Overpass API')
    countries, data_timestamp = await query_overpass(_QUERY, timeout=300, must_return=True)
    countries_geoms: list[BaseGeometry] = []
    countries_geoms_q: list[dict[float, BaseGeometry]] = []

    for country in tqdm(countries, desc='Processing geometry'):
        outer_segments = []
        inner_segments = []

        for member in country.get('members', []):
            if member['type'] != 'way':
                continue

            if member['role'] == 'outer':
                outer_segments.append(tuple((g['lon'], g['lat']) for g in member['geometry']))
            elif member['role'] == 'inner':
                inner_segments.append(tuple((g['lon'], g['lat']) for g in member['geometry']))

        try:
            outer_polys = (Polygon(s) for s in _connect_segments(outer_segments))
            inner_polys = (Polygon(s) for s in _connect_segments(inner_segments))

            outer_simple = tuple(p for p in outer_polys if p.is_valid)
            inner_simple = tuple(p for p in inner_polys if p.is_valid)

            if not outer_simple:
                raise Exception('No outer polygons')

            outer_union: BaseGeometry = unary_union(outer_simple)
            inner_union: BaseGeometry = unary_union(inner_simple)
            countries_geoms.append(outer_union.difference(inner_union))
            countries_geoms_q.append({})

        except Exception as e:
            country_name = country['tags'].get('name', '??')
            raise Exception(f'Error processing {country_name}') from e

    topo = tp.Topology(countries_geoms, prequantize=False)
    del countries_geoms  # free memory

    for q in tqdm(sorted(GEOJSON_QUALITIES), desc='Simplifying geometry'):
        topo.toposimplify(q, inplace=True)
        features = serialize_as_geojson(topo.to_dict())['features']
        for country_geoms_q, feature in zip(countries_geoms_q, features, strict=True):
            country_geoms_q[q] = orient(shape(feature['geometry']).buffer(0))  # fix geometry

    del topo  # free memory
    result = []

    for country, country_geoms_q in zip(countries, countries_geoms_q, strict=True):
        tags = country['tags']
        point = country_geoms_q[BEST_GEOJSON_QUALITY].representative_point()

        result.append(
            OSMCountry(
                tags=tags,
                geometry=country_geoms_q,
                representative_point=mapping(point),
            )
        )

    return result, data_timestamp
