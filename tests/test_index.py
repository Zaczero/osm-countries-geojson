from html.parser import HTMLParser

import pytest
from jinja2 import UndefinedError

from index import Download, listing


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.elements = []
        self.feed(content.decode())

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_minified_index_preserves_downloads_metadata_and_analytics():
    files: dict[str, Download] = {
        f'osm-countries-{quality}.geojson{suffix}': {'size': 1048576}
        for quality in ('0-00001', '0-0001', '0-001', '0-01', '0-1')
        for suffix in ('', '.br', '.gz', '.zst')
    }
    content = listing('example.invalid', files, 1791811131, 'G-EXAMPLE')
    page = Page(content)
    links = [attrs['href'] for tag, attrs in page.elements if tag == 'a' and attrs.get('itemprop') == 'contentUrl']
    assert links == ['/' + name for name in files if name.endswith(('.br', '.gz', '.zst'))]
    assert sum(attrs.get('itemtype') == 'https://schema.org/DataDownload' for _, attrs in page.elements) == 15
    assert any(tag == 'a' and attrs.get('rel') == 'license' for tag, attrs in page.elements)
    assert any(tag == 'link' and attrs.get('href') == 'https://example.invalid/' for tag, attrs in page.elements)
    assert any(tag == 'time' and attrs['datetime'] == '2026-10-12T13:18:51+00:00' for tag, attrs in page.elements)
    assert sum(tag == 'script' for tag, _ in page.elements) == 2
    assert b'G-EXAMPLE' in content
    assert b'\n  ' not in content


def test_template_escapes_download_names_before_minification():
    name = 'country"><script>alert(1)</script>.geojson.zst'
    page = Page(listing('example.invalid', {name: {'size': 1234}}, 1791811131, 'G-EXAMPLE'))
    assert sum(tag == 'script' for tag, _ in page.elements) == 2
    assert any(tag == 'a' and attrs.get('href') == '/' + name for tag, attrs in page.elements)


def test_missing_file_size_fails_instead_of_publishing_an_incomplete_index():
    with pytest.raises(UndefinedError):
        listing('example.invalid', {'country.geojson.zst': {}}, 1791811131, 'G-EXAMPLE')  # pyright: ignore[reportArgumentType] -- Deliberately malformed template data.
