import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import boto3
import sentry_sdk
from botocore.config import Config
from cloudflare import Cloudflare

from config import DOWNLOAD_NAMES, GEOJSON_DIR, NAME, PUBLICATION, REVISION
from index import Download, content_type, listing
from release import activate, collect, verify_public_index

CACHE_CONTROL = 'public, max-age=300, no-transform'


class PublishError(Exception):
    pass


class Artifact(Download):
    sha256: str


def publish(client, bucket: str, directory: Path, revision: str) -> tuple[str, dict[str, Artifact]]:
    paths = {path.name: path for path in directory.iterdir()}
    if set(paths) != set(DOWNLOAD_NAMES):
        raise PublishError('Output does not match the country-file inventory')
    files: dict[str, Artifact] = {}
    for name, path in sorted(paths.items()):
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise PublishError(f'Not a nonempty regular file: {name}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files[name] = {'size': path.stat().st_size, 'sha256': digest}
    raw = min((name for name in files if name.endswith('.geojson')), key=lambda name: files[name]['size'])
    data = json.loads((directory / raw).read_bytes())
    timestamp = data['features'][0]['properties']['timestamp']
    generated = {
        '': listing(PUBLICATION['hostname'], files, timestamp, PUBLICATION['googleAnalyticsID']),
        'robots.txt': (
            'User-agent: *\n' + ''.join(f'Disallow: /{name}\n' for name in files if name.endswith('.geojson'))
        ).encode(),
    }
    for name, content in generated.items():
        files[name] = {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    manifest = {
        'files': files,
        'dataTimestamp': timestamp,
        'sourceRevision': revision,
    }
    document = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    release = hashlib.sha256(document).hexdigest()
    prefix = f'releases/{release}/'
    for name, item in files.items():
        with sentry_sdk.start_span(op='r2.upload', name=name or 'index.html'):
            if name in generated:
                body = generated[name]
                checksum = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
                client.put_object(
                    Bucket=bucket,
                    Key=prefix + name,
                    Body=body,
                    ContentLength=item['size'],
                    ContentMD5=checksum,
                    ContentType=content_type(name),
                    CacheControl=CACHE_CONTROL,
                )
            else:
                with paths[name].open('rb') as stream:
                    checksum = base64.b64encode(hashlib.file_digest(stream, 'md5').digest()).decode()
                    stream.seek(0)
                    client.put_object(
                        Bucket=bucket,
                        Key=prefix + name,
                        Body=stream,
                        ContentLength=item['size'],
                        ContentMD5=checksum,
                        ContentType=content_type(name),
                        CacheControl=CACHE_CONTROL,
                    )
            response = client.get_object(Bucket=bucket, Key=prefix + name)
            with response['Body'] as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != item['sha256'] or response['ContentLength'] != item['size']:
                raise PublishError(f'Uploaded object integrity mismatch: {name or "/"}')
            if (
                response['ContentType'] != content_type(name)
                or response.get('ContentEncoding')
                or response['CacheControl'] != CACHE_CONTROL
            ):
                raise PublishError(f'Uploaded object metadata mismatch: {name or "/"}')
        print(f'Uploaded and verified {name or "/"} ({item["size"]} bytes)', file=sys.stderr, flush=True)
    client.put_object(
        Bucket=bucket,
        Key=prefix + 'manifest.json',
        Body=document,
        ContentType='application/json',
    )
    with client.get_object(Bucket=bucket, Key=prefix + 'manifest.json')['Body'] as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != release:
            raise PublishError('Uploaded release manifest integrity mismatch')
    return release, files


def main():
    client = boto3.client(
        's3',
        config=Config(
            request_checksum_calculation='when_required',
            response_checksum_validation='when_required',
        ),
    )
    if os.environ['GITHUB_SHA'] != REVISION:
        raise PublishError('Checkout does not match the workflow revision')
    bucket = NAME
    release, files = publish(client, bucket, GEOJSON_DIR, REVISION)
    with sentry_sdk.start_span(op='r2.activate', name='Activate verified release'):
        with Cloudflare() as cloudflare:
            activate(cloudflare, PUBLICATION['hostname'], PUBLICATION['zone'], release, files)
        verify_public_index(PUBLICATION['hostname'], files['']['sha256'])
    with sentry_sdk.start_span(op='r2.collect', name='Remove superseded releases'):
        collect(client, bucket, release)
    print(f'Published release {release}', file=sys.stderr, flush=True)


if __name__ == '__main__':
    from monitoring import init_sentry

    init_sentry()
    with sentry_sdk.start_transaction(op='task', name='publish-geojson'):
        main()
