"""Optional, display-only place names. Never changes route identity or coordinates.

LocationIQ reuses the existing integration and key. Both the server switch and
the explicit request switch must be enabled. No lookup happens on list/read,
publication, or language switching. Reverse results describe nearby features;
they are not proof of settlement containment.
"""
import asyncio
from collections import OrderedDict, deque
from copy import deepcopy
import math
import os
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.normalizers import sanitize_text


class _TextModel(BaseModel):
    model_config = ConfigDict(extra='ignore')

    @field_validator('*', mode='before')
    @classmethod
    def trim_strings(cls, value):
        if isinstance(value, str):
            if len(value) > 500:
                raise ValueError('Текст не должен превышать 500 символов')
            return sanitize_text(value.strip(), max_length=500) or None
        return value


class LocalizedText(_TextModel):
    label: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=500)


class LocalizedNames(_TextModel):
    ru: str | None = Field(None, max_length=200)
    ka: str | None = Field(None, max_length=200)


class LocalizedPresentation(BaseModel):
    model_config = ConfigDict(extra='ignore')
    ru: LocalizedText | None = None
    ka: LocalizedText | None = None


class PlaceContext(_TextModel):
    relation: Literal['within', 'nearby', 'region']
    names: LocalizedNames
    source: str | None = Field(None, max_length=60)
    country_iso: str | None = Field(None, pattern=r'^[A-Za-z]{2}$')
    key: str | None = Field(None, max_length=150)
    distance_m: float | None = Field(None, ge=0, le=1000000, allow_inf_nan=False)

    @field_validator('distance_m', mode='before')
    @classmethod
    def numeric_distance(cls, value):
        if isinstance(value, bool):
            raise ValueError('Расстояние должно быть числом')
        return value


def _nonempty(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {key: clean for key, item in value.items() if (clean := _nonempty(item)) not in (None, '', {})}
    return value


def presentation_fields(data, existing=None, *, country=None):
    """Merge only same-point omissions. Context is never routing evidence."""
    incoming = {field: _nonempty(getattr(data, field, None)) for field in ('localized', 'context')}
    identity = data.key or (getattr(data, 'settlement_key', None) if data.kind == 'settlement' else None)
    same = (isinstance(existing, dict) and existing.get('kind') == data.kind
            and existing.get('key') == identity and existing.get('lat') == data.lat
            and existing.get('lon') == data.lon
            and existing.get('country_iso') == country)
    out = {}
    for field, value in incoming.items():
        old = existing.get(field) if isinstance(existing, dict) else None
        if same and old:
            value = _merge(old, value or {})
        elif not same and old and value == old:
            # A copied old snapshot does not describe a newly moved point.
            value = None
        if value:
            out[field] = value
    context = out.get('context')
    if context:
        if not context.get('names') or (context.get('country_iso') and context['country_iso'].upper() != country):
            out.pop('context', None)
        elif context.get('country_iso'):
            context['country_iso'] = context['country_iso'].upper()
    return out


def _merge(first, second):
    result = deepcopy(first)
    for key, value in second.items():
        result[key] = _merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else deepcopy(value)
    return result


def canonical_presentation(location):
    """Use actual dictionary names, without translating fallback text."""
    names = {}
    if location.get('name_ru'):
        names['ru'] = location['name_ru']
    if location.get('name_ge') and _has_language(location['name_ge'], 'ka'):
        names['ka'] = location['name_ge']
    out = {'localized': {language: {'label': name} for language, name in names.items()}} if names else {}
    if names and location.get('kind') == 'settlement':
        out['context'] = {'relation': 'within', 'names': names, 'source': 'city_catalog',
                          'country_iso': location['country_iso'], 'key': location['key']}
    return out


def _has_language(text, language):
    return bool(re.search(r'[\u10a0-\u10ff\u1c90-\u1cbf]' if language == 'ka' else r'[\u0400-\u04ff]', text or ''))


def _text(value, limit=500):
    return sanitize_text(value.strip(), max_length=limit) if isinstance(value, str) else ''


_cache = OrderedDict()
_inflight = {}
_lookup_times = deque()
_CACHE_LIMIT = 256
_CACHE_SECONDS = 3600
_MAX_INFLIGHT = 8
_MAX_LOOKUPS_PER_MINUTE = 20


def _provider_config():
    from app.services import geocoder
    enabled = os.getenv('LOCATION_PRESENTATION_ENABLED', '').lower() in ('1', 'true', 'yes')
    return enabled, geocoder.LOCATIONIQ_KEY or os.getenv('LOCATIONIQ_KEY', ''), geocoder.LOCATIONIQ_BASE


async def _reverse_snapshots(lat, lon, key, base):
    """At most two bounded requests; returned feature coordinates are ignored."""
    async with httpx.AsyncClient(timeout=2.0, follow_redirects=False) as client:
        async def fetch(language):
            try:
                response = await client.get(base + '/reverse.php', params={
                    'key': key, 'lat': lat, 'lon': lon, 'format': 'json',
                    'accept-language': language, 'addressdetails': 1,
                    'namedetails': 1, 'showdistance': 1, 'normalizeaddress': 0,
                })
                response.raise_for_status()
                if len(response.content) > 131072:
                    return None
                value = response.json()
                return value if isinstance(value, dict) else None
            except (httpx.HTTPError, ValueError, TypeError):
                return None
        return await asyncio.gather(fetch('ru'), fetch('ka'))


async def _cached_snapshots(lat, lon, country, key, base):
    cache_key = (lat, lon, country, key)
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and cached[0] > now:
        _cache.move_to_end(cache_key)
        return deepcopy(cached[1])
    _cache.pop(cache_key, None)
    task_key = (id(asyncio.get_running_loop()), cache_key)
    if task_key in _inflight:
        return deepcopy(await asyncio.shield(_inflight[task_key]))
    if len(_inflight) >= _MAX_INFLIGHT:
        return []
    while _lookup_times and _lookup_times[0] <= now - 60:
        _lookup_times.popleft()
    if len(_lookup_times) >= _MAX_LOOKUPS_PER_MINUTE:
        return []
    _lookup_times.append(now)
    async def load():
        try:
            rows = await asyncio.wait_for(_reverse_snapshots(lat, lon, key, base), timeout=2.5)
        except (TimeoutError, httpx.HTTPError):
            rows = []
        _cache[cache_key] = (time.monotonic() + (_CACHE_SECONDS if any(rows) else 30), deepcopy(rows))
        while len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
        return rows
    task = asyncio.create_task(load())
    _inflight[task_key] = task
    try:
        return deepcopy(await asyncio.shield(task))
    finally:
        _inflight.pop(task_key, None)


def _feature_id(row):
    if row.get('osm_id') and row.get('osm_type'):
        return str(row['osm_type']) + ':' + str(row['osm_id'])
    return str(row.get('place_id') or '')


def _snapshot_presentation(rows, country, label, label_mode):
    localized, locality_names, region_names = {}, {}, {}
    feature = None
    for language, row in zip(('ru', 'ka'), rows):
        if not isinstance(row, dict):
            continue
        address = row.get('address')
        if not isinstance(address, dict) or str(address.get('country_code', '')).upper() != country:
            continue
        identity = _feature_id(row)
        if feature is not None and (not identity or not feature or identity != feature):
            continue
        feature = identity
        names = row.get('namedetails') if isinstance(row.get('namedetails'), dict) else {}
        full_address = _text(row.get('display_name'))
        text = {}
        if _has_language(full_address, language):
            text['address'] = full_address
        # A reverse feature may be a different nearby object. Its alternative
        # names qualify only when they identify the selected automatic POI.
        aliases = {_text(value, 200).casefold() for key, value in names.items() if key == 'name' or key.startswith('name:')}
        try:
            close = 0 <= float(row.get('distance', math.inf)) <= 50
        except (ValueError, TypeError):
            close = False
        translated = _text(names.get('name:' + language), 200)
        if identity and label_mode == 'auto' and close and label.casefold() in aliases and translated:
            text['label'] = translated
        if text:
            localized[language] = text
        locality = next((_text(address.get(key), 200) for key in ('city', 'town', 'village', 'hamlet', 'locality') if address.get(key)), '')
        region = next((_text(address.get(key), 200) for key in ('state', 'county', 'region') if address.get(key)), '')
        if _has_language(locality, language):
            locality_names[language] = locality
        if _has_language(region, language):
            region_names[language] = region
    result = {'localized': localized} if localized else {}
    names = locality_names or region_names
    if names:
        result['context'] = {'relation': 'nearby' if locality_names else 'region', 'names': names,
                             'country_iso': country, 'source': 'locationiq_reverse'}
    return result


async def enrich_presentation(lat, lon, country, *, label='', label_mode=None, requested=False):
    enabled, key, base = _provider_config()
    if requested is not True or not enabled or not key:
        return {}
    rows = await _cached_snapshots(lat, lon, country, key, base)
    return _snapshot_presentation(rows, country, label, label_mode)
