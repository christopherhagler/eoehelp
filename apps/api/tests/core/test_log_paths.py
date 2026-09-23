"""No logger may print the resolved request path or the client address.

The privacy policy states, as a fact about the system, that technical logs hold
"the request method, the route pattern rather than the address you visited, the
response status, how long it took, and a request id". Two loggers contradicted
it: uvicorn's access log and slowapi's. A resolved path is a patient's symptom
date or a row id, and because the path is percent-decoded before either logger
sees it, an unauthenticated caller could put newlines in one and forge whole
log lines — corrupting the record that exists to answer "was my data accessed".

`logger.disabled` is process-global and sticky, so a later `dictConfig` would
undo it silently. These tests are what would notice.
"""

import logging

import pytest
from httpx import AsyncClient

from eoehelp_api.observability import (
    _ACCESS_LOGGERS,
    _PATH_LOGGERS,
    configure_logging,
    get_logger,
)


class TestLoggerConfiguration:
    def test_access_loggers_are_disabled(self) -> None:
        configure_logging(environment="local", debug=False)
        for name in _ACCESS_LOGGERS:
            assert logging.getLogger(name).disabled is True, f"{name} would log request paths"

    def test_path_loggers_are_filtered_but_still_report_storage_failures(self) -> None:
        """Filtered rather than disabled on purpose: slowapi's logger is also
        where a rate-limit storage outage is reported, and the limiter does not
        swallow errors, so losing that signal would be worse than the leak."""
        configure_logging(environment="local", debug=False)
        for name in _PATH_LOGGERS:
            logger = logging.getLogger(name)
            assert logger.disabled is False
            assert logger.filters, f"{name} has no filter to drop request paths"

            leaking = logging.LogRecord(
                name, logging.WARNING, __file__, 1, "ratelimit exceeded at endpoint: /x", None, None
            )
            keeping = logging.LogRecord(
                name, logging.WARNING, __file__, 1, "Failed to rate limit. %s", ("boom",), None
            )
            assert not all(f.filter(leaking) for f in logger.filters)
            assert all(f.filter(keeping) for f in logger.filters)


class TestNoPathReachesTheLog:
    async def test_a_crafted_path_does_not_reach_the_log(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        """Checked against stdout, not only `caplog`.

        structlog is configured with `PrintLoggerFactory`, so application log
        lines are written straight to stdout and never become stdlib records —
        a `caplog`-only assertion here captures nothing and passes whatever the
        application logs. Both are checked: stdout for the application's own
        lines, `caplog` for anything a library emits through stdlib.

        The legal route also refuses this by pattern now, but every other route
        still takes a free-form path, and this is what guards those.
        """
        marker = "FORGED-LOG-LINE"
        with caplog.at_level(logging.DEBUG):
            await client.get(f"/api/v1/legal/documents/x%0a{marker}")
            await client.get(f"/api/v1/me/symptoms/{marker}")

        written = capfd.readouterr()
        assert marker not in written.out
        assert marker not in written.err
        # Positive control: without this the test also passes if the middleware
        # stops logging requests altogether.
        assert "/legal/documents/{document_id}" in written.out
        for record in caplog.records:
            assert marker not in record.getMessage()
            assert marker not in str(getattr(record, "args", "") or "")

    async def test_the_assertion_above_can_actually_see_a_log_line(
        self, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """Proves the check is not vacuous.

        The previous version of the test above asserted only over `caplog`,
        which structlog never reaches, so it passed by capturing nothing. A
        security assertion that cannot fail is worse than no assertion, so this
        one demonstrates that the capture works.
        """
        configure_logging(environment="local", debug=False)
        get_logger(__name__).info("probe.visible", path="/a/b")

        written = capfd.readouterr()
        assert "probe.visible" in written.out
