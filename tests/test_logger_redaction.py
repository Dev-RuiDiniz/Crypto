import io
import logging

from utils.logger import RedactSecretsFilter


def test_redaction_filter_hides_sensitive_terms():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactSecretsFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.redaction")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info("payload apiSecret=abc token=xyz password=123")
    out = stream.getvalue()

    assert "apiSecret" not in out
    assert "token" not in out
    assert "password" not in out
    assert "***REDACTED***" in out
