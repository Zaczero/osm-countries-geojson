from collections import defaultdict
from itertools import chain, cycle, islice, pairwise
from typing import Sequence

import networkx as nx
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from tqdm import tqdm

from config import BEST_GEOJSON_QUALITY, GEOJSON_QUALITIES
from models.osm_country import OSMCountry
from overpass import query_overpass

_QUERY = (
    'rel[boundary=administrative][admin_level=2]["ISO3166-1"][name];'
    'out geom qt;'
)


def _connect_segments(segments: Sequence[tuple[tuple]]) -> Sequence[Sequence[tuple]]:
    # count occurrences of each node
    node_count = defaultdict(int)
    for node in chain.from_iterable(segments):
        node_count[node] += 1

    # validate that all segments are closed (i.e., start and end at intersections)
    if any(node_count[s[0]] < 2 or node_count[s[-1]] < 2 for s in segments):
        raise ValueError('Segments must be closed')

    # node = intersection, node_count > 1
    # edge = segment between intersections
    G = nx.DiGraph()

    # build the graph
    for segment in segments:
        subsegment_start = None
        subsegment = []
        for node in segment:
            # intersection node
            if node_count[node] > 1:
                if subsegment_start:
                    if len(subsegment) == 0:
                        G.add_edge(subsegment_start, node)
                        G.add_edge(node, subsegment_start)
                    elif len(subsegment) == 1:
                        first = subsegment[0]
                        G.add_edge(subsegment_start, first)
                        G.add_edge(first, node)
                        G.add_edge(node, first)
                        G.add_edge(first, subsegment_start)
                    else:
                        first = subsegment[0]
                        last = subsegment[-1]
                        G.add_edge(subsegment_start, first)
                        G.add_edge(first, last, subsegment=subsegment)
                        G.add_edge(last, node)
                        G.add_edge(node, last)
                        G.add_edge(last, first, subsegment=subsegment[::-1])
                        G.add_edge(first, subsegment_start)
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
        aligned = tuple(chain(
            islice(segment, min_idx, len(segment) - 1),
            islice(segment, min_idx + 1)))

        # normalize orientation
        if segment[-1] < segment[1]:
            aligned = aligned[::-1]

        return aligned

    for c in nx.simple_cycles(G):
        c = tuple(islice(cycle(c), len(c) + 1))  # close the cycle

        merged_unordered: list[list] = []

        for u, v in pairwise(c):
            if subsegment := G[u][v].get('subsegment'):
                merged_unordered.append(subsegment)
            else:
                merged_unordered.append([u, v])

        first = merged_unordered[0]
        second = merged_unordered[1]

        # proper orientation of the first segment
        if first[0] in (second[0], second[-1]):
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
    result = []

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

        outer_polys = tuple(Polygon(s) for s in _connect_segments(outer_segments))
        inner_polys = tuple(Polygon(s) for s in _connect_segments(inner_segments))
        geometry: dict[float, Polygon | MultiPolygon] = {}

        try:
            for q in GEOJSON_QUALITIES:
                outer_simple = (p.simplify(q) for p in outer_polys)
                outer_simple = tuple(p for p in outer_simple if p.is_valid)
                inner_simple = (p.simplify(q) for p in inner_polys)
                inner_simple = tuple(p for p in inner_simple if p.is_valid)

                if not outer_simple:
                    raise Exception('No outer polygons')

                outer_union = unary_union(outer_simple)
                inner_union = unary_union(inner_simple)
                geometry[q] = outer_union.difference(inner_union)
        except Exception as e:
            country_name = country['tags'].get('name', '??')
            raise Exception(f'Error processing {country_name}') from e

        representative_point = geometry[BEST_GEOJSON_QUALITY].representative_point()

        result.append(OSMCountry(
            tags=country['tags'],
            geometry=geometry,
            representative_point=representative_point,
        ))

    return tuple(result), data_timestamp
