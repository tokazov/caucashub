"""Typed route endpoints. Server-owned countries and immutable map coordinates.

Catalogue endpoints resolve without network. Arbitrary pins require a signed
server resolution; the client cannot choose a country to cross scope filters.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


class RouteLocationInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    kind: Literal['settlement', 'border_checkpoint', 'point']
    key: str | None = Field(None, max_length=150)
    label: str = Field(min_length=1, max_length=200)
    country_iso: str | None = Field(None, pattern=r'^[A-Za-z]{2}$')
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    address: str | None = Field(None, max_length=500)
    settlement_id: int | None = Field(None, ge=1, strict=True)
    settlement_key: str | None = Field(None, max_length=150)
    resolution_token: str | None = Field(None, max_length=1000)

    @field_validator('lat', 'lon', mode='before')
    @classmethod
    def finite_coordinate(cls, value):
        if isinstance(value, bool):
            raise ValueError('Координаты должны быть числами')
        return value

    @field_validator('label', 'address')
    @classmethod
    def trim_text(cls, value, info):
        if value is None:
            return value
        from app.services.normalizers import sanitize_text
        value = sanitize_text(value.strip(), max_length=500)
        if not value:
            if info.field_name == 'address':
                return None
            raise ValueError('Укажите название точки')
        return value


def _payload(value):
    return value.model_dump() if isinstance(value, BaseModel) else dict(value)


@lru_cache(maxsize=1)
def location_catalog():
    path = Path(__file__).with_name('location_catalog.json')
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = raw.get('locations', raw.get('points', [])) if isinstance(raw, dict) else raw
    return rows


def _catalog_row(row, lang='ru'):
    names = row.get('labels', {})
    ru = row.get('name_ru') or row.get('label_ru') or names.get('ru') or row.get('label') or ''
    ge = row.get('name_ge') or row.get('label_ge') or names.get('ge') or names.get('ka') or ru
    en = row.get('name_en') or row.get('label_en') or names.get('en') or ru
    country = row['country_iso'].upper()
    aliases = list(dict.fromkeys([ru, ge, en, *row.get('aliases', [])]))
    return {'kind': row.get('kind', 'border_checkpoint'), 'key': row['key'],
            'label': ge if lang in ('ge', 'ka') else en if lang == 'en' else ru,
            'name_ru': ru, 'name_ge': ge, 'name_en': en,
            'country_iso': country, 'lat': float(row['lat']), 'lon': float(row['lon']),
            'address': row.get('address') or ru, 'settlement_id': None,
            'settlement_key': None, 'aliases': aliases, 'source': 'catalog'}


def catalogue_identity(key):
    for row in location_catalog():
        if row.get('key') == key:
            return _catalog_row(row)
    return None


def catalogue_key_for_alias(value):
    from app.services.city_identity import normalized_city
    needle = normalized_city(value)
    keys = {row['key'] for row in location_catalog()
            if value == row['key'] or any(needle == normalized_city(alias)
                for alias in _catalog_row(row)['aliases'])}
    return next(iter(keys)) if len(keys) == 1 else None


def _canonical_city_location(city, lang='ru'):
    label = city.name_ge or city.name_ru if lang in ('ge', 'ka') else city.name_en if lang == 'en' else city.name_ru
    return {'kind': 'settlement', 'key': city.key, 'label': label,
            'name_ru': city.name_ru, 'name_ge': city.name_ge, 'name_en': city.name_en,
            'country_iso': city.country_iso, 'lat': city.lat, 'lon': city.lon,
            'address': label, 'settlement_id': city.id, 'settlement_key': city.key,
            'aliases': city.public_aliases(), 'source': 'city_catalog'}


def suggest_locations(registry, query='', lang='ru', scope=None, limit=250):
    from app.services.city_identity import normalized_city
    needle = normalized_city(query)
    rows = [_catalog_row(row, lang) for row in location_catalog()]
    rows += [_canonical_city_location(city, lang) for city in registry.by_key.values()
             if city.lat is not None and city.lon is not None]
    if scope == 'local':
        rows = [row for row in rows if row['country_iso'] == 'GE']
    if needle:
        rows = [row for row in rows if any(needle in normalized_city(alias)
                for alias in row['aliases'])]
        rows.sort(key=lambda row: (not any(needle == normalized_city(alias) for alias in row['aliases']),
                                  row['kind'] != 'border_checkpoint', row['label']))
    return rows[:limit]


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def resolution_token(lat, lon, country, now=None):
    payload = json.dumps({'v': 1, 'lat': lat, 'lon': lon, 'country_iso': country,
                          'exp': int(now if now is not None else time.time()) + 86400},
                         sort_keys=True, separators=(',', ':')).encode()
    signature = hmac.new(settings.SECRET_KEY.encode(), b'route-location-v1:' + payload, hashlib.sha256).digest()
    return _encode(payload) + '.' + _encode(signature)


def verified_token(token, lat, lon, country=None, now=None):
    try:
        encoded, signature = token.split('.')
        payload = _decode(encoded)
        expected = hmac.new(settings.SECRET_KEY.encode(), b'route-location-v1:' + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signature)):
            raise ValueError()
        data = json.loads(payload)
        if (data.get('v') != 1 or data['exp'] < int(now if now is not None else time.time())
                or data['lat'] != lat or data['lon'] != lon
                or (country and country.upper() != data['country_iso'])):
            raise ValueError()
        return data['country_iso']
    except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('Выберите точку на карте повторно: подтверждение координат недействительно / აირჩიეთ წერტილი ხელახლა') from None


async def resolve_country(lat, lon):
    # Root-owned country resolver never trusts the browser country label.
    from app.services.location_country import resolve_country as resolver
    return await asyncio.to_thread(resolver, lat, lon)


def declared_settlement(data, registry, country):
    if not data.settlement_id and not data.settlement_key:
        return None
    if registry is None:
        raise ValueError('Не удалось проверить населённый пункт')
    city = registry.resolve(city_id=data.settlement_id, city_key=data.settlement_key)
    if (city is None or city.country_iso != country
            or (data.settlement_key and city.key != data.settlement_key)):
        raise ValueError('Населённый пункт и страна точки не совпадают')
    return city


async def resolve_map_location(data, registry=None):
    data = RouteLocationInput.model_validate({'kind': 'point', 'label': 'Точка на карте', **_payload(data)})
    country = await resolve_country(data.lat, data.lon)
    if isinstance(country, dict):
        country = country.get('country_iso')
    if not isinstance(country, str) or not re.fullmatch('[A-Za-z]{2}', country):
        raise ValueError('Не удалось однозначно определить страну точки. Уточните точку или выберите КПП из списка / დააზუსტეთ წერტილი ან აირჩიეთ გამშვები პუნქტი')
    country = country.upper()
    if data.country_iso and data.country_iso.upper() != country:
        raise ValueError('Страна точки не совпадает с координатами / ქვეყანა არ ემთხვევა კოორდინატებს')
    city = declared_settlement(data, registry, country)
    return {'kind': 'point', 'key': None, 'label': data.label,
            'lat': data.lat, 'lon': data.lon, 'country_iso': country,
            'address': data.address or data.label, 'settlement_id': city.id if city else None,
            'settlement_key': city.key if city else None,
            'aliases': list(dict.fromkeys([data.label, *(city.public_aliases() if city else [])])),
            'resolution_token': resolution_token(data.lat, data.lon, country)}


def _same_saved_point(data, existing):
    return (isinstance(existing, dict) and existing.get('kind') == 'point'
            and existing.get('lat') == data.lat and existing.get('lon') == data.lon
            and existing.get('country_iso') == (data.country_iso or existing.get('country_iso')))


async def normalize_location(db, registry, raw, existing=None):
    from app.services.city_identity import resolve_publication_city
    data = RouteLocationInput.model_validate(raw)
    if data.kind == 'settlement':
        city = registry.resolve(city_id=data.settlement_id, city_key=data.key or data.settlement_key)
        if not city or ((data.key or data.settlement_key) and city.key != (data.key or data.settlement_key)):
            raise ValueError('Выберите согласованный населённый пункт из списка / აირჩიეთ დასახლება სიიდან')
        if data.country_iso and data.country_iso.upper() != city.country_iso:
            raise ValueError('Страна и населённый пункт не совпадают')
        # A settlement selection means its canonical point. Street pins use kind=point.
        if not (math.isclose(data.lat, city.lat, abs_tol=0.00001)
                and math.isclose(data.lon, city.lon, abs_tol=0.00001)):
            raise ValueError('Для точного адреса выберите точку на карте')
        name, city_id = await resolve_publication_city(db, registry, city.name_ru, city_key=city.key)
        out = _canonical_city_location(city)
        out.update(label=name, settlement_id=city_id, address=data.address or name)
        return out
    if data.kind == 'border_checkpoint' or (data.key and catalogue_identity(data.key)):
        out = catalogue_identity(data.key)
        if out is None or out['kind'] != data.kind:
            raise ValueError('Неизвестный пограничный переход')
        if (data.country_iso and data.country_iso.upper() != out['country_iso']) or not (
                math.isclose(data.lat, out['lat'], abs_tol=0.00001)
                and math.isclose(data.lon, out['lon'], abs_tol=0.00001)):
            raise ValueError('Выбранная точка и координаты КПП не совпадают')
        out.update(label=data.label, address=data.address or out['address'])
        out['aliases'] = list(dict.fromkeys([data.label, *out['aliases']]))
        return out
    if _same_saved_point(data, existing):
        country = existing['country_iso']
    else:
        country = verified_token(data.resolution_token, data.lat, data.lon, data.country_iso)
    city = declared_settlement(data, registry, country)
    city_id = None
    if city:
        _, city_id = await resolve_publication_city(db, registry, city.name_ru, city_key=city.key)
    return {'kind': 'point', 'key': None, 'label': data.label, 'lat': data.lat,
            'lon': data.lon, 'country_iso': country, 'address': data.address or data.label,
            'settlement_id': city_id, 'settlement_key': city.key if city else None,
            'aliases': list(dict.fromkeys([data.label, *(city.public_aliases() if city else [])]))}


async def apply_route_locations(db, data, existing=None):
    from app.services.city_identity import city_registry, resolve_publication_city
    registry = await city_registry(db)
    routing_requested = existing is None or any(
        data.get(side + '_location') is not None or (side + '_city' in data and data[side + '_city'] != getattr(existing, side + '_city'))
        for side in ('from', 'to'))
    for side in ('from', 'to'):
        location_field = side + '_location'
        name_field, id_field, key_field = side + '_city', side + '_city_id', side + '_city_key'
        if location_field in data and data[location_field] is not None:
            location = await normalize_location(db, registry, data[location_field],
                                                getattr(existing, location_field, None) if existing else None)
            data[location_field] = location
            settlement = registry.resolve(city_id=location.get('settlement_id'), city_key=location.get('settlement_key')) if location.get('settlement_key') else None
            data[name_field] = settlement.name_ru if settlement else location['label'][:100]
            data[id_field] = location.get('settlement_id')
            data.pop(key_field, None)
            if existing is None or hasattr(existing, side + '_address'):
                data[side + '_address'] = location['address']
            continue
        fields = (name_field, id_field, key_field)
        if existing is not None and not any(field in data for field in fields):
            # Omitting a location in an unrelated edit must preserve exact coordinates.
            data.pop(location_field, None)
            continue
        old_location = getattr(existing, location_field, None) if existing else None
        if old_location:
            unchanged = (data.get(name_field, getattr(existing, name_field)) == getattr(existing, name_field)
                         and not data.get(key_field) and data.get(id_field) in (None, getattr(existing, id_field)))
            if unchanged:
                data.pop(location_field, None)
                continue
            # A plain-city edit explicitly clears an old pin; no stale coordinates.
            data[location_field] = None
        name = data.get(name_field) or (getattr(existing, name_field) if existing else '')
        city_id, city_key = data.get(id_field), data.pop(key_field, None)
        if existing is not None and city_id is None and not city_key and name == getattr(existing, name_field) and registry.endpoint(name, getattr(existing, id_field)) is None:
            data[name_field], data[id_field] = name, getattr(existing, id_field)
            continue
        data[name_field], data[id_field] = await resolve_publication_city(db, registry, name, city_id, city_key)
    merged = {side: data.get(side + '_location', getattr(existing, side + '_location', None) if existing else None)
              for side in ('from', 'to')}
    countries = []
    for side in ('from', 'to'):
        location = merged[side]
        if location:
            countries.append(location['country_iso'])
        else:
            identity = registry.endpoint(data.get(side + '_city', getattr(existing, side + '_city', '') if existing else ''),
                                         data.get(side + '_city_id', getattr(existing, side + '_city_id', None) if existing else None))
            countries.append(identity.country_iso if identity else None)
    if all(countries) and countries[0] == countries[1] != 'GE' and routing_requested:
        raise ValueError('В пилоте доступны перевозки внутри Грузии и международные маршруты')
    return registry


def location_filter_clause(model, side, *, text=None, key=None):
    """Filter special object by stable key or own catalogue language aliases."""
    from app.services.city_identity import normalized_city
    column = getattr(model, side + '_location')
    keys = []
    if key and catalogue_identity(key) is None:
        raise ValueError('Неизвестный идентификатор точки')
    if key and catalogue_identity(key):
        row = catalogue_identity(key)
        if text and normalized_city(text) not in {normalized_city(alias) for alias in row['aliases']}:
            raise ValueError('Точка и её идентификатор не совпадают')
        keys.append(key)
    needle = normalized_city(text)
    if needle:
        keys.extend(row['key'] for row in location_catalog()
                    if any(needle in normalized_city(alias) for alias in _catalog_row(row)['aliases']))
    if not keys:
        return None
    return column['key'].as_string().in_(set(keys))
