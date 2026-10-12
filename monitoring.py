import os

import sentry_sdk

from errors import OSMDataError


def init_sentry() -> None:
    sentry_sdk.init(
        ignore_errors=[OSMDataError],
        max_value_length=4096,
        send_default_pii=False,
        auto_session_tracking=False,
        traces_sample_rate=1.0,
        trace_propagation_targets=[],
        ca_certs=os.environ.get('NIX_SSL_CERT_FILE') or os.environ.get('SSL_CERT_FILE'),
    )
    if run := os.environ.get('GITHUB_RUN_ID'):
        sentry_sdk.set_tag('github.run_id', run)
        sentry_sdk.set_tag('github.run_attempt', os.environ.get('GITHUB_RUN_ATTEMPT'))
