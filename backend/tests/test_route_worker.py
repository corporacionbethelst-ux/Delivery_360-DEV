"""Celery worker boundaries, safe retries and deterministic resource cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from app.workers import route_analysis_worker as worker


@pytest.mark.parametrize("identifier", ["invalid", None, 42])
def test_invalid_delivery_identifiers_do_not_start_database_work(identifier):
    assert worker.analyze_route_deviations.run(identifier) == {
        "success": False,
        "reason": "Invalid delivery UUID",
    }


@pytest.mark.asyncio
async def test_manual_review_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(
        worker, "run_analysis", AsyncMock(side_effect=ValueError("sensitive details"))
    )
    result = await asyncio.to_thread(worker.analyze_route_deviations.run, str(uuid4()))
    assert result == {"success": False, "reason": "Route requires manual review"}


@pytest.mark.asyncio
async def test_retry_does_not_store_raw_exception_or_coordinates(monkeypatch):
    monkeypatch.setattr(
        worker, "run_analysis", AsyncMock(side_effect=RuntimeError("secret-db-url"))
    )
    retry = MagicMock(side_effect=RuntimeError("retry marker"))
    monkeypatch.setattr(worker.analyze_route_deviations, "retry", retry)
    with pytest.raises(RuntimeError, match="retry marker"):
        await asyncio.to_thread(worker.analyze_route_deviations.run, str(uuid4()))
    assert str(retry.call_args.kwargs["exc"]) == "Route analysis unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_engine_is_disposed_even_when_analysis_fails(monkeypatch, failure):
    engine = SimpleNamespace(dispose=AsyncMock())
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(worker, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(worker, "async_sessionmaker", lambda *a, **kw: lambda: session)
    analyze = AsyncMock(
        side_effect=ValueError("invalid plan") if failure else None,
        return_value={"success": True},
    )
    monkeypatch.setattr(
        worker, "RouteService", lambda db: SimpleNamespace(analyze_route=analyze)
    )
    if failure:
        with pytest.raises(ValueError):
            await worker.run_analysis(uuid4())
    else:
        assert await worker.run_analysis(uuid4()) == {"success": True}
    engine.dispose.assert_awaited_once()
