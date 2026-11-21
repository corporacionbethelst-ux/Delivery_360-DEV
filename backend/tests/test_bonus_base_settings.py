from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.dialects import postgresql
from app.core.exceptions import ValidationError
from app.services.bonus_base_settings import load_bonus_bases


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.0049999999999999999999", Decimal("0.0049999999999999999999")),
        ("99999999.984999999999999999", Decimal("99999999.984999999999999999")),
        ('"2.505"', "2.505"),
        ("0", Decimal("0")),
        ("null", None),
        ("true", True),
        ("[]", []),
        ("{}", {}),
    ],
)
async def test_textual_json_reader_preserves_tokens_and_shared_lock(raw, expected):
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [
        SimpleNamespace(key="rider_delivery_bonus", raw_value=raw)
    ]
    db.execute.return_value = result
    values = await load_bonus_bases(db, ["rider_delivery_bonus"])
    assert values == {"rider_delivery_bonus": expected}
    if isinstance(expected, Decimal):
        assert isinstance(values["rider_delivery_bonus"], Decimal)
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "CAST(platform_settings.value AS TEXT)" in sql and "FOR SHARE" in sql
    assert "ORDER BY platform_settings.key" in sql
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_reader_rejects_malformed_json_and_unknown_keys_without_writing():
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = [
        SimpleNamespace(key="rider_delivery_bonus", raw_value="broken")
    ]
    db.execute.return_value = result
    with pytest.raises(ValidationError):
        await load_bonus_bases(db, ["rider_delivery_bonus"])
    with pytest.raises(ValueError):
        await load_bonus_bases(db, ["commission_percentage"])
    db.commit.assert_not_awaited()
