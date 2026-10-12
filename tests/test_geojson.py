import json

import pytest
from shapely.geometry import Polygon

from main import write_geojson
from osm_countries_gen import OSMCountry
from overpass import parse_response


def test_overpass_decoder_preserves_coordinates_and_unicode_tags():
    data = {
        'osm3s': {'timestamp_osm_base': '2026-10-12T13:18:51Z'},
        'elements': [
            {
                'id': 12345678901,
                'tags': {'name': 'Polska — 日本'},
                'members': [{'geometry': [{'lon': 17.0000001, 'lat': 51.1099999}]}],
            }
        ],
    }
    countries, timestamp = parse_response(json.dumps(data, ensure_ascii=False).encode())
    assert countries == data['elements']
    assert timestamp == 1791811131.0


def test_overpass_partial_result_is_not_accepted():
    with pytest.raises(RuntimeError):
        parse_response(b'{"remark": "runtime error: Query timed out", "elements": [{"id": 1}]}')


def test_streamed_geojson_preserves_the_complete_feature_collection(tmp_path):
    polygon = Polygon([(0, 0), (2, 0), (2, 2), (0, 0)])
    point = {'type': 'Point', 'coordinates': [1, 0.5]}
    countries = [
        OSMCountry(tags={'name': name}, geometry={0.01: polygon}, representative_point=point)
        for name in ('Polska — 日本', 'Second')
    ]
    target = tmp_path / 'countries.geojson'
    write_geojson(target, countries, 1791811131.0, 0.01)
    expected = {
        'type': 'FeatureCollection',
        'name': 'countries',
        'crs': {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}},
        'features': [
            {
                'type': 'Feature',
                'properties': {'tags': {'name': name}, 'timestamp': 1791811131.0, 'representative_point': point},
                'geometry': {'type': 'Polygon', 'coordinates': [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]]},
            }
            for name in ('Polska — 日本', 'Second')
        ],
    }
    assert target.read_bytes() == json.dumps(expected, ensure_ascii=False).encode()
