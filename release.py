import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import cast

from cloudflare import Cloudflare
from cloudflare.types.rulesets import RewriteRule
from cloudflare.types.rulesets.rewrite_rule import ActionParametersURIURIPath
from cloudflare.types.rulesets.rule_edit_params import RewriteRuleActionParameters


def activate(cloudflare: Cloudflare, hostname: str, zone: str, release: str, files: Collection[str]) -> set[str]:
    ruleset = cloudflare.rulesets.phases.get('http_request_transform', zone_id=zone)
    reference = 'fleet_r2_' + re.sub('[^a-z0-9]', '_', hostname) + '_release'
    rule = next(item for item in ruleset.rules if item.ref == reference)
    if (
        not isinstance(rule, RewriteRule)
        or rule.id is None
        or (parameters := rule.action_parameters) is None
        or not isinstance(uri := parameters.uri, ActionParametersURIURIPath)
        or uri.path.expression is None
    ):
        raise RuntimeError('Download rule is not a release-path rewrite')
    current = re.search(r'/releases/([0-9a-f]{64})', uri.path.expression)
    if current is None:
        raise RuntimeError('Download rule does not identify a release')
    if current[1] == release:
        previous = re.fullmatch(r'Previous release: ([0-9a-f]{64})', rule.description or '')
        if previous is None:
            raise RuntimeError('Download rule has no previous-release marker')
        previous_release = previous[1]
    else:
        previous_release = current[1]
        # Routing and rollback retention change in the same atomic rule update.
        cloudflare.rulesets.rules.edit(
            rule.id,
            ruleset_id=ruleset.id,
            zone_id=zone,
            ref=reference,
            description=f'Previous release: {previous_release}',
            expression=f'http.host eq {json.dumps(hostname)}',
            action='rewrite',
            # The SDK's URI union omits the API's combined path and query rewrite.
            action_parameters=cast(
                RewriteRuleActionParameters,
                cast(
                    object,
                    {
                        'uri': {
                            'path': {'expression': f'concat("/releases/{release}", http.request.uri.path)'},
                            'query': {'value': ''},
                        },
                    },
                ),
            ),
            enabled=True,
        )
    urls = [f'https://{hostname}{prefix}/{name}' for name in files for prefix in ('', f'/releases/{release}')]
    for batch in batched(urls, 30):  # noqa: B911 -- The final API batch may be partial.
        cloudflare.cache.purge(zone_id=zone, files=list(batch))
    return {release, previous_release}


def verify_public_index(hostname: str, expected_hash: str) -> None:
    context = ssl.create_default_context(
        cafile=os.environ.get('NIX_SSL_CERT_FILE') or os.environ.get('SSL_CERT_FILE'),
    )
    deadline = time.monotonic() + 180
    while True:
        with urllib.request.urlopen(f'https://{hostname}/', context=context, timeout=30) as response:
            actual = hashlib.file_digest(response, 'sha256').hexdigest()
        if actual == expected_hash:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Public index did not converge to the accepted release')
        time.sleep(3)


def collect(client, bucket: str, retained: set[str]) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=7)
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='releases/'):
        keys = [
            {'Key': item['Key']}
            for item in page.get('Contents', [])
            if item['Key'].split('/')[1] not in retained and item['LastModified'] < cutoff
        ]
        if keys:
            result = client.delete_objects(Bucket=bucket, Delete={'Objects': keys, 'Quiet': True})
            if result.get('Errors'):
                raise RuntimeError(f'Release cleanup failed: {result["Errors"]}')
    cutoff = datetime.now(UTC) - timedelta(days=1)
    for page in client.get_paginator('list_multipart_uploads').paginate(Bucket=bucket, Prefix='releases/'):
        for upload in page.get('Uploads', []):
            if upload['Initiated'] < cutoff:
                client.abort_multipart_upload(Bucket=bucket, Key=upload['Key'], UploadId=upload['UploadId'])
