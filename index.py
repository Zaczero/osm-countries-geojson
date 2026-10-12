import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class Download(TypedDict):
    size: int


def content_type(name: str) -> str:
    if not name:
        return 'text/html; charset=utf-8'
    if name == 'robots.txt':
        return 'text/plain; charset=utf-8'
    return {
        '.geojson': 'application/geo+json',
        '.gz': 'application/gzip',
        '.br': 'application/octet-stream',
        '.zst': 'application/zstd',
    }[Path(name).suffix]


def listing(hostname: str, files: Mapping[str, Download], timestamp: float, measurement_id: str) -> bytes:
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / 'templates'),
        autoescape=True,
        undefined=StrictUndefined,
    )
    page = environment.get_template('index.html.jinja').render(
        canonical=f'https://{hostname}/',
        files=files,
        content_type=content_type,
        source_time=datetime.fromtimestamp(timestamp, UTC),
        measurement_id=measurement_id,
    )
    return subprocess.run(
        ['minify', '--type', 'text/html'],  # noqa: S607 -- Nix supplies the minifier.
        input=page.encode(),
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
