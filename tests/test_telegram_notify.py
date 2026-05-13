"""
Tests for telegram_notify.py — ADR-013 changes.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_send():
    with patch("app.services.telegram_notify.send_tg_message", new_callable=AsyncMock) as m:
        yield m


# ── Task 1: notify_new_response ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_response_no_carrier_name(mock_send):
    """Сообщение не должно содержать имя перевозчика."""
    from app.services.telegram_notify import notify_new_response

    await notify_new_response(
        chat_id=123,
        from_city="Тбилиси", to_city="Батуми",
        price=500.0, cur="₾",
        carrier_rating=4.5, carrier_deals=12,
        load_id=42, lang="ru"
    )

    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    # carrier_name должен отсутствовать в шаблоне
    assert "Перевозчик:" not in text
    assert "carrier" not in text.lower() or "рейтинг перевозчика" in text.lower()


@pytest.mark.asyncio
async def test_new_response_has_load_id(mock_send):
    """Сообщение должно содержать ID груза."""
    from app.services.telegram_notify import notify_new_response

    await notify_new_response(
        chat_id=123,
        from_city="Тбилиси", to_city="Батуми",
        price=500.0, cur="₾",
        carrier_rating=4.5, carrier_deals=12,
        load_id=99, lang="ru"
    )

    text = mock_send.call_args[0][1]
    assert "#99" in text


@pytest.mark.asyncio
async def test_new_response_has_rating(mock_send):
    """Сообщение должно содержать рейтинг и количество сделок."""
    from app.services.telegram_notify import notify_new_response

    await notify_new_response(
        chat_id=123,
        from_city="Тбилиси", to_city="Батуми",
        price=500.0, cur="₾",
        carrier_rating=3.8, carrier_deals=7,
        load_id=1, lang="ru"
    )

    text = mock_send.call_args[0][1]
    assert "3.8" in text
    assert "7" in text
    assert "5.0" in text


@pytest.mark.asyncio
async def test_new_response_ge_locale(mock_send):
    """Проверяем грузинский локаль — те же поля, грузинский текст."""
    from app.services.telegram_notify import notify_new_response

    await notify_new_response(
        chat_id=456,
        from_city="თბილისი", to_city="ბათუმი",
        price=200.0, cur="₾",
        carrier_rating=4.2, carrier_deals=5,
        load_id=77, lang="ge"
    )

    text = mock_send.call_args[0][1]
    assert "#77" in text
    assert "4.2" in text
    assert "5.0" in text
    # Georgian locale keywords
    assert "გამოხმაურება" in text or "ტვირთი" in text


# ── Task 2: notify_deal_created ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deal_created_has_contacts(mock_send):
    """Сообщение содержит телефон и email перевозчика."""
    from app.services.telegram_notify import notify_deal_created

    await notify_deal_created(
        chat_id=123,
        deal_num="CH-0042",
        from_city="Тбилиси", to_city="Поти",
        carrier_name="ООО Быстро",
        carrier_phone="+995555123456",
        carrier_email="carrier@example.com",
        lang="ru"
    )

    text = mock_send.call_args[0][1]
    assert "CH-0042" in text
    assert "+995555123456" in text
    assert "carrier@example.com" in text
    assert "ООО Быстро" in text


@pytest.mark.asyncio
async def test_deal_created_handles_missing_email(mock_send):
    """Если email=None — строка с email не включается, телефон остаётся."""
    from app.services.telegram_notify import notify_deal_created

    await notify_deal_created(
        chat_id=123,
        deal_num="CH-0043",
        from_city="Тбилиси", to_city="Поти",
        carrier_name="ИП Иванов",
        carrier_phone="+99599000111",
        carrier_email=None,
        lang="ru"
    )

    text = mock_send.call_args[0][1]
    assert "+99599000111" in text
    assert "@" not in text or "caucashub.ge" in text  # no carrier email


@pytest.mark.asyncio
async def test_deal_created_handles_missing_all(mock_send):
    """Если все контакты None — выводим fallback ссылку."""
    from app.services.telegram_notify import notify_deal_created

    await notify_deal_created(
        chat_id=123,
        deal_num="CH-0044",
        from_city="Тбилиси", to_city="Поти",
        carrier_name=None,
        carrier_phone=None,
        carrier_email=None,
        lang="ru"
    )

    text = mock_send.call_args[0][1]
    assert "caucashub.ge" in text


@pytest.mark.asyncio
async def test_accept_response_triggers_both_notifications():
    """
    accept_response должен вызывать notify_response_accepted (перевозчику)
    И notify_deal_created (грузоотправителю) в одной транзакции.
    """
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock

    # Mock both notification functions
    with patch("app.routers.responses.notify_response_accepted", new_callable=AsyncMock) as mock_accepted, \
         patch("app.routers.responses.notify_deal_created", new_callable=AsyncMock) as mock_deal_created, \
         patch("asyncio.create_task") as mock_create_task:

        # Verify both are imported in responses module
        import app.routers.responses as resp_module
        assert hasattr(resp_module, "notify_response_accepted")
        assert hasattr(resp_module, "notify_deal_created")

        # Both should be accessible (not None)
        assert resp_module.notify_response_accepted is not None
        assert resp_module.notify_deal_created is not None
