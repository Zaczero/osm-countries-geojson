import gzip
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import chain, cycle, islice, pairwise
from typing import Any, NamedTuple

import networkx as nx
import numpy as np
import sentry_sdk
from shapely import Polygon
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import orient, unary_union

from config import BEST_GEOJSON_QUALITY, GEOJSON_QUALITIES
from errors import OSMDataError
from overpass import query_overpass
from toposimplify import Topology
from utils import progress


class OSMCountry(NamedTuple):
    tags: dict[str, str]
    geometry: dict[float, BaseGeometry]
    representative_point: dict[str, Any]


type Coordinate = tuple[float, float]


_QUERY = (
    '('
    'rel[boundary~"^(administrative|disputed)$"][admin_level=2]["ISO3166-1"][name];'
    'rel(1703814);'  # Palestinian Territories
    ');'
    'out geom qt;'
)


def _connect_segments(segments: Sequence[tuple[Coordinate, ...]]) -> set[tuple[Coordinate, ...]]:
    # count occurrences of each node
    node_count = defaultdict(int)
    for node in chain.from_iterable(segments):
        node_count[node] += 1

    # validate that all segments are closed (i.e., start and end at intersections)
    for s in segments:
        if len(s) < 2:
            raise OSMDataError('Boundary way has fewer than two coordinates')
        node_id_start = s[0]
        node_id_end = s[-1]
        if node_count[node_id_start] < 2 or node_count[node_id_end] < 2:
            raise OSMDataError(f'Segments must be closed ({node_id_start}, {node_id_end})')

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
    def connected_normalize(segment: list[Coordinate]) -> tuple[Coordinate, ...]:
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

        merged_unordered: list[list[Coordinate]] = []

        for u, v in pairwise(c):
            if subsegment := graph[u][v].get('subsegment'):
                merged_unordered.append(subsegment)
            else:
                merged_unordered.append([u, v])

        if len(merged_unordered) < 2:
            # this realistically will mean broken data: a single node, a small loop, etc.
            print(f'⚠️ Single-segment cycle: {c!r}')
            continue

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
                raise RuntimeError('Graph cycle contains disconnected segments')
        else:
            if len(merged) >= 4 and merged[1] != merged[-2]:
                connected.add(connected_normalize(merged))

    return connected


async def get_osm_countries() -> tuple[Sequence[OSMCountry], float]:
    print('Querying Overpass API')
    with sentry_sdk.start_span(op='http.client', name='Fetch OSM country boundaries'):
        countries, data_timestamp = await query_overpass(_QUERY, http_timeout=300, must_return=True)
    countries_geoms: list[BaseGeometry] = []
    countries_geoms_q: list[dict[float, BaseGeometry]] = []

    for country in progress(countries, desc='Processing geometry'):
        outer_segments = []
        inner_segments = []
        try:
            for member in country.get('members', []):
                if member['type'] != 'way':
                    continue
                if member['role'] == 'outer':
                    outer_segments.append(tuple((g['lon'], g['lat']) for g in member['geometry']))
                elif member['role'] == 'inner':
                    inner_segments.append(tuple((g['lon'], g['lat']) for g in member['geometry']))

            if not outer_segments:
                raise OSMDataError('No outer boundary ways')
            outer_simple = tuple(p for p in (Polygon(s) for s in _connect_segments(outer_segments)) if p.is_valid)
            inner_simple = tuple(p for p in (Polygon(s) for s in _connect_segments(inner_segments)) if p.is_valid)
            if not outer_simple:
                raise RuntimeError('Could not reconstruct any valid outer polygons')

            outer_union: BaseGeometry = unary_union(outer_simple)
            inner_union: BaseGeometry = unary_union(inner_simple)
            countries_geoms.append(outer_union.difference(inner_union))
            countries_geoms_q.append({})
            del country['members']

        except Exception as e:
            country_name = country['tags'].get('name', '??')
            e.add_note(f'Processing relation/{country["id"]}: {country_name}')
            if not isinstance(e, OSMDataError):
                # The unhandled-exception hook runs outside asyncio's context.
                scope = sentry_sdk.get_global_scope()
                scope.set_context('osm', {'relation_id': country['id'], 'source_timestamp': data_timestamp})
                scope.add_attachment(
                    bytes=lambda country=country: gzip.compress(
                        json.dumps({
                            'osm3s': {'timestamp_osm_base': datetime.fromtimestamp(data_timestamp, UTC).isoformat()},
                            'elements': [country],
                        }).encode()
                    ),
                    filename=f'relation-{country["id"]}.json.gz',
                    content_type='application/gzip',
                )
            raise

    topo = Topology(countries_geoms)  # pyright: ignore[reportArgumentType]
    del countries_geoms
    for q in progress(sorted(GEOJSON_QUALITIES), desc='Simplifying geometry'):
        with sentry_sdk.start_span(op='geo.simplify', name=f'Simplify tolerance {q}'):
            for country_geoms_q, geom in zip(countries_geoms_q, topo.simplify(q), strict=True):
                country_geoms_q[q] = orient(geom.buffer(0))  # fix geometry
    del topo

    result: list[OSMCountry] = []
    for country, country_geoms_q in zip(countries, countries_geoms_q, strict=True):
        point = country_geoms_q[BEST_GEOJSON_QUALITY].representative_point()
        result.append(
            OSMCountry(
                tags=country['tags'],
                geometry=country_geoms_q,
                representative_point=mapping(point),
            )
        )
    return result, data_timestamp
