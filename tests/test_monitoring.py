import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CAPTURE_SETUP = """
import os
from pathlib import Path
import sentry_sdk
from sentry_sdk.transport import Transport

class RecordingTransport(Transport):
    def capture_envelope(self, envelope):
        with Path(os.environ['CAPTURE_EVENTS']).open('ab') as output:
            for item in envelope.items:
                if item.type in ('event', 'transaction'):
                    output.write(item.payload.get_bytes() + b'\\n')
                elif item.type == 'attachment':
                    Path(item.headers['filename']).write_bytes(item.payload.get_bytes())

sdk_init = sentry_sdk.init
def init(*args, **kwargs):
    return sdk_init(*args, transport=RecordingTransport, **kwargs)
sentry_sdk.init = init
"""


@pytest.fixture
def sentry_run(tmp_path):
    root = Path(__file__).resolve().parents[1]
    captured = tmp_path / 'events.jsonl'

    def run(script):
        result = subprocess.run(  # noqa: S603 -- Test scripts replace only the SDK's external transport.
            [sys.executable, '-c', CAPTURE_SETUP + script],
            cwd=tmp_path,
            env={
                'HOME': str(tmp_path),
                'PATH': os.environ['PATH'],
                'PYTHONPATH': str(root),
                'GIT_DIR': str(root / '.git'),
                'SENTRY_DSN': 'http://public@example.invalid/1',
                'CAPTURE_EVENTS': str(captured),
            },
            capture_output=True,
            timeout=30,
            check=False,
        )
        events = [json.loads(line) for line in captured.read_bytes().splitlines()] if captured.exists() else []
        return result, events

    return run


@pytest.mark.parametrize(
    ('exception', 'reported'),
    [('RuntimeError', True), ('ValueError', True), ('OSMDataError', False)],
)
def test_unhandled_errors_report_only_application_failures(sentry_run, exception, reported):
    result, events = sentry_run(
        'from monitoring import init_sentry\n'
        'from errors import OSMDataError\n'
        'init_sentry()\n'
        'def fail():\n'
        '    relation_id = 1234567\n'
        f'    raise {exception}("failed operation")\n'
        'fail()\n',
    )
    assert result.returncode != 0
    assert bool(events) is reported
    if reported:
        assert events[0]['exception']['values'][-1]['type'] == exception
        frames = events[0]['exception']['values'][-1]['stacktrace']['frames']
        assert frames[-1]['vars']['relation_id'] == '1234567'


def test_generation_reports_stage_timings(sentry_run, tmp_path):
    script = """
import asyncio
import runpy
from httpx import AsyncClient, MockTransport, Response
import utils

def respond(request):
    if request.url.path == '/api/interpreter':
        rings = (
            ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)),
            ((1, 0), (2, 0), (2, 1), (1, 1), (1, 0)),
        )
        return Response(200, json={
            'osm3s': {'timestamp_osm_base': '2026-10-12T13:18:51Z'},
            'elements': [{
                'type': 'relation', 'id': index, 'tags': {'name': f'Country {index}'},
                'members': [{'type': 'way', 'role': 'outer',
                             'geometry': [{'lon': x, 'lat': y} for x, y in ring]}],
            } for index, ring in enumerate(rings, 1)],
        })
    return Response(200, json={'features': [{
        'type': 'Feature', 'properties': {'NAME': 'Fixture'},
        'geometry': {'type': 'Polygon', 'coordinates': [
            [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]],
        ]},
    }]})

asyncio.run(utils.HTTP.aclose())
utils.HTTP = AsyncClient(transport=MockTransport(respond))
runpy.run_module('generate', run_name='__main__')
asyncio.run(utils.HTTP.aclose())
"""
    result, events = sentry_run(script)
    assert result.returncode == 0, result.stderr.decode()
    transactions = [event for event in events if event.get('type') == 'transaction']
    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction['transaction'] == 'generate-geojson'
    operations = [span['op'] for span in transaction['spans']]
    assert operations.count('geo.generate') == 1
    assert operations.count('geo.validate') == 1
    assert operations.count('geo.simplify') == 5
    assert operations.count('file.write') == 5
    assert operations.count('compression') == 15
    assert len(list((tmp_path / 'geojson').glob('*.geojson'))) == 5
    assert len(list((tmp_path / 'geojson').iterdir())) == 20


def test_relation_failure_attaches_original_input_once(sentry_run, tmp_path):
    country = {
        'type': 'relation',
        'id': 1234567,
        'tags': {'name': 'Broken boundary'},
        'members': [{'type': 'way', 'role': 'outer'}],
    }
    script = f"""
import asyncio
from httpx import AsyncClient, MockTransport, Response
import utils
from monitoring import init_sentry

init_sentry()
asyncio.run(utils.HTTP.aclose())
utils.HTTP = AsyncClient(transport=MockTransport(lambda request: Response(200, json={{
    'osm3s': {{'timestamp_osm_base': '2026-10-12T13:18:51Z'}},
    'elements': [{country!r}],
}})))
from osm_countries_gen import get_osm_countries
asyncio.run(get_osm_countries())
"""
    result, events = sentry_run(script)
    assert result.returncode != 0
    errors = [event for event in events if 'exception' in event]
    assert len(errors) == 1
    assert errors[0]['contexts']['osm']['relation_id'] == 1234567
    attached = json.loads(gzip.decompress((tmp_path / 'relation-1234567.json.gz').read_bytes()))
    assert attached['elements'] == [country]
    assert attached['osm3s']['timestamp_osm_base'] == '2026-10-12T13:18:51+00:00'
