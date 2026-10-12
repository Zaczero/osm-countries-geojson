# ruff: noqa: S106 -- Synthetic credentials are sent only through the mock transport.
import json
from types import SimpleNamespace

import httpx
import pytest
from cloudflare import APIError, Cloudflare

from release import activate, collect


class RulesEndpoint:
    def __init__(self, release, fail=None):
        self.fail = fail
        self.rule = {
            'id': 'rule',
            'version': '1',
            'last_updated': '2026-10-12T12:00:00Z',
            'action': 'rewrite',
            'enabled': True,
            'expression': 'http.host eq "example.invalid"',
            'ref': 'fleet_r2_example_invalid_release',
            'description': 'GeoJSON downloads',
            'action_parameters': {
                'uri': {
                    'path': {
                        'expression': f'concat("/releases/{release}", http.request.uri.path)',
                    }
                }
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == 'PATCH':
            declaration = json.loads(request.content)
            if not declaration.get('expression'):
                return httpx.Response(400, json={'success': False, 'errors': [{'message': 'Missing expression'}]})
            if self.fail == 'before':
                return httpx.Response(503, json={'success': False, 'errors': [{'message': 'Unavailable'}]})
            self.rule.update(declaration)
            if self.fail == 'after':
                raise httpx.ReadError('Response lost after admission', request=request)
        result = {
            'id': 'ruleset',
            'name': 'Default',
            'kind': 'zone',
            'phase': 'http_request_transform',
            'version': '1',
            'last_updated': '2026-10-12T12:00:00Z',
            'rules': [self.rule],
        }
        return httpx.Response(200, json={'success': True, 'errors': [], 'messages': [], 'result': result})


def test_completed_admission_routes_to_the_new_release():
    endpoint = RulesEndpoint('a' * 64)
    with Cloudflare(api_token='fixture', http_client=httpx.Client(transport=httpx.MockTransport(endpoint))) as client:
        activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
    assert endpoint.rule['action_parameters']['uri']['path']['expression'] == (
        f'concat("/releases/{"b" * 64}", http.request.uri.path)'
    )


@pytest.mark.parametrize('failure', ['before', 'after'])
def test_interrupted_admission_can_be_retried(failure):
    endpoint = RulesEndpoint('a' * 64, fail=failure)
    with Cloudflare(
        api_token='fixture',
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(endpoint)),
    ) as client:
        with pytest.raises(APIError):
            activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
        endpoint.fail = None
        activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
    assert endpoint.rule['action_parameters']['uri']['path']['expression'] == (
        f'concat("/releases/{"b" * 64}", http.request.uri.path)'
    )


def test_unchanged_admission_needs_no_previous_release_marker():
    endpoint = RulesEndpoint('a' * 64)
    with Cloudflare(api_token='fixture', http_client=httpx.Client(transport=httpx.MockTransport(endpoint))) as client:
        activate(client, 'example.invalid', 'zone', 'a' * 64, [''])
    assert endpoint.rule['action_parameters']['uri']['path']['expression'] == (
        f'concat("/releases/{"a" * 64}", http.request.uri.path)'
    )


class ReleaseBucket:
    def __init__(self):
        self.keys = {'releases/current/data', 'releases/current/manifest.json', 'releases/old/data'}
        self.uploads = {'unfinished'}

    def get_paginator(self, operation):
        if operation == 'list_objects_v2':
            pages = [{'Contents': [{'Key': key} for key in self.keys]}]
        else:
            pages = [{'Uploads': [{'Key': 'releases/abandoned/data', 'UploadId': 'unfinished'}]}]
        return SimpleNamespace(paginate=lambda **_: pages)

    def delete_objects(self, **request):
        self.keys.difference_update(item['Key'] for item in request['Delete']['Objects'])
        return {}

    def abort_multipart_upload(self, **request):
        self.uploads.remove(request['UploadId'])


def test_collection_keeps_only_the_current_release():
    bucket = ReleaseBucket()
    collect(bucket, 'fixture', 'current')
    assert bucket.keys == {'releases/current/data', 'releases/current/manifest.json'}
    assert not bucket.uploads
