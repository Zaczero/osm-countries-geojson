# ruff: noqa: S106 -- Synthetic credentials are sent only through the mock transport.
import json

import httpx
import pytest
from cloudflare import APIError, Cloudflare

from release import activate


class RulesEndpoint:
    def __init__(self, release, previous, fail=None):
        self.fail = fail
        self.rule = {
            'id': 'rule',
            'version': '1',
            'last_updated': '2026-10-12T12:00:00Z',
            'action': 'rewrite',
            'enabled': True,
            'expression': 'http.host eq "example.invalid"',
            'ref': 'fleet_r2_example_invalid_release',
            'description': f'Previous release: {previous}',
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


def test_completed_admission_retains_both_accepted_generations():
    endpoint = RulesEndpoint('a' * 64, 'c' * 64)
    with Cloudflare(api_token='fixture', http_client=httpx.Client(transport=httpx.MockTransport(endpoint))) as client:
        retained = activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
    assert retained == {'b' * 64, 'a' * 64}
    assert endpoint.rule['description'] == f'Previous release: {"a" * 64}'


@pytest.mark.parametrize('failure', ['before', 'after'])
def test_interrupted_admission_preserves_previous_release_on_retry(failure):
    endpoint = RulesEndpoint('a' * 64, 'c' * 64, fail=failure)
    with Cloudflare(
        api_token='fixture',
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(endpoint)),
    ) as client:
        with pytest.raises(APIError):
            activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
        endpoint.fail = None
        actual = 'a' * 64 if failure == 'before' else 'b' * 64
        retained = activate(client, 'example.invalid', 'zone', actual, [''])
    assert retained == ({'a' * 64, 'c' * 64} if failure == 'before' else {'b' * 64, 'a' * 64})


def test_unchanged_admission_keeps_the_previous_generation():
    endpoint = RulesEndpoint('a' * 64, 'c' * 64)
    with Cloudflare(api_token='fixture', http_client=httpx.Client(transport=httpx.MockTransport(endpoint))) as client:
        retained = activate(client, 'example.invalid', 'zone', 'a' * 64, [''])
    assert retained == {'a' * 64, 'c' * 64}


def test_first_ci_admission_retains_the_existing_fleet_release():
    endpoint = RulesEndpoint('a' * 64, None)
    endpoint.rule['description'] = 'Accepted R2 release for example.invalid'
    with Cloudflare(api_token='fixture', http_client=httpx.Client(transport=httpx.MockTransport(endpoint))) as client:
        retained = activate(client, 'example.invalid', 'zone', 'b' * 64, [''])
    assert retained == {'b' * 64, 'a' * 64}
