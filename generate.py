import asyncio

import sentry_sdk

from compress import compress_geojson
from main import main
from monitoring import init_sentry

if __name__ == '__main__':
    init_sentry()
    with sentry_sdk.start_transaction(op='task', name='generate-geojson'):
        asyncio.run(main())
        compress_geojson()
