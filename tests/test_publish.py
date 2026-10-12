import hashlib
import io
import json

import pytest

from publish import PublishError, publish


class Bucket:
    def __init__(self, fail_key=None):
        self.objects = {}
        self.metadata = {}
        self.fail_key = fail_key

    def put_object(self, **request):
        if self.fail_key and request['Key'].endswith(self.fail_key):
            raise ConnectionResetError('upload failed')
        body = request['Body']
        self.objects[request['Key']] = body.read() if isinstance(body, io.IOBase) else body
        self.metadata[request['Key']] = {key: request[key] for key in ('ContentType', 'CacheControl') if key in request}

    def get_object(self, **request):
        content = self.objects[request['Key']]
        return {
            'Body': io.BytesIO(content),
            'ContentLength': len(content),
            **self.metadata[request['Key']],
        }


@pytest.fixture
def artifact(tmp_path):
    raw = b'{"features":[{"properties":{"timestamp":1791760000}}]}'
    for quality in ('0-00001', '0-0001', '0-001', '0-01', '0-1'):
        for suffix in ('', '.br', '.gz', '.zst'):
            (tmp_path / f'osm-countries-{quality}.geojson{suffix}').write_bytes(raw)
    return tmp_path


def test_verified_release_identifies_its_source_and_file_bytes(artifact):
    bucket = Bucket()
    release, _ = publish(bucket, 'uploads', artifact, 'source-revision')
    document = bucket.objects[f'releases/{release}/manifest.json']
    assert hashlib.sha256(document).hexdigest() == release
    result = json.loads(document)
    assert result['sourceRevision'] == 'source-revision'
    assert result['dataTimestamp'] == 1791760000
    assert len(result['files']) == 22
    name = 'osm-countries-0-01.geojson.zst'
    assert result['files'][name]['sha256'] == hashlib.sha256((artifact / name).read_bytes()).hexdigest()


def test_failed_upload_never_marks_a_release_complete(artifact):
    bucket = Bucket(fail_key='osm-countries-0-01.geojson.zst')
    with pytest.raises(ConnectionResetError):
        publish(bucket, 'uploads', artifact, 'source-revision')
    assert not any(key.endswith('/manifest.json') for key in bucket.objects)


@pytest.mark.parametrize('defect', ['missing', 'extra', 'symlink'])
def test_invalid_release_inventory_is_rejected(artifact, defect):
    target = artifact / 'osm-countries-0-01.geojson'
    if defect == 'missing':
        target.unlink()
    elif defect == 'extra':
        (artifact / '.env').write_text('private')
    else:
        target.unlink()
        target.symlink_to(artifact / 'osm-countries-0-01.geojson.zst')
    with pytest.raises(PublishError):
        publish(Bucket(), 'uploads', artifact, 'source-revision')
