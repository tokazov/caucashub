"""P2 тесты: normalizers + matchers"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_p2_norm.db")
os.environ.setdefault("SECRET_KEY", "test-p2")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
from app.services.normalizers import normalize_phone, normalize_tax_id


# Task 7 — Georgian phone format
def test_normalize_phone_georgian_local():
    assert normalize_phone('0551234567') == '+995551234567'

def test_normalize_phone_georgian_with_995():
    assert normalize_phone('995551234567') == '+995551234567'

def test_normalize_phone_georgian_with_plus():
    assert normalize_phone('+995551234567') == '+995551234567'

def test_normalize_phone_russian():
    assert normalize_phone('89991234567') == '+79991234567'


# Task 12 — normalize_tax_id
def test_normalize_tax_id_valid():
    assert normalize_tax_id('123456789') == '123456789'

def test_normalize_tax_id_with_dashes():
    assert normalize_tax_id('12-345-6789') == '123456789'

def test_normalize_tax_id_invalid_returns_input():
    """Невалидный ИНН должен вернуть исходную строку, не None."""
    result = normalize_tax_id('12345')
    assert result == '12345'
    assert result is not None

def test_normalize_tax_id_none():
    assert normalize_tax_id(None) is None


# Task 11 — city normalization
def test_city_normalize_hyphens():
    from app.services.subscription_matcher import _normalize
    assert _normalize('Ростов-на-Дону') == 'ростов на дону'

def test_city_normalize_whitespace():
    from app.services.subscription_matcher import _normalize
    assert _normalize('Нижний  Новгород') == 'нижний новгород'

def test_city_normalize_strips():
    from app.services.subscription_matcher import _normalize
    assert _normalize('  Тбилиси  ') == 'тбилиси'

def test_city_normalize_empty():
    from app.services.subscription_matcher import _normalize
    assert _normalize('') == ''


# Task 8 — Decimal conversion
def test_convert_returns_decimal():
    from decimal import Decimal
    from app.services.exchange_rate import convert_gel_to_usd
    result = convert_gel_to_usd(100, 2.7)
    assert isinstance(result, Decimal)

def test_convert_rounds_half_up():
    from decimal import Decimal
    from app.services.exchange_rate import convert_gel_to_usd
    result = convert_gel_to_usd(Decimal('100'), Decimal('3'))
    assert result == Decimal('33.33')

def test_convert_usd_to_gel_decimal():
    from decimal import Decimal
    from app.services.exchange_rate import convert_usd_to_gel
    result = convert_usd_to_gel(Decimal('10'), Decimal('2.73'))
    assert isinstance(result, Decimal)
    assert result == Decimal('27.30')
