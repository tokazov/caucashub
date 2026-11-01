"""Local display of a saved endpoint when a new act is first rendered.

Only existing city/catalogue names and saved localization are used. Exact point
labels and postal addresses must never be replaced by their containing city.
This module performs no lookup, mutation or translation-provider request.
"""
import re
import unicodedata

from app.services.route_locations import catalogue_identity, catalogue_key_for_alias


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _display_key(value):
    # City search intentionally keeps only text before a comma. Document
    # display comparisons must retain every street/house/POI component.
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', _text(value)).casefold())


def _whole_city(value, registry, city_id=None):
    if any(mark in value for mark in (',', ';', '\n', '\r')):
        return None
    return registry.endpoint(value, city_id)


def _known_name(value, registry, language, city_id=None):
    raw = _text(value)
    if not raw:
        return raw
    city = _whole_city(raw, registry, city_id)
    if city:
        return _text(city.name_ge if language == 'ka' else city.name_ru) or raw
    if city_id is None and not any(mark in raw for mark in (',', ';', '\n', '\r')):
        point = catalogue_identity(catalogue_key_for_alias(raw))
        if point:
            return _text(point.get('name_ge' if language == 'ka' else 'name_ru')) or raw
    return raw


def _localized(location, language, field):
    values = location.get('localized')
    values = values.get(language) if isinstance(values, dict) else None
    return _text(values.get(field)) if isinstance(values, dict) else ''


def _broad_name(value, location, registry):
    """A city/context label alone is insufficient localization of a precise pin."""
    if not value:
        return False
    if _whole_city(value, registry):
        return True
    context = location.get('context')
    names = context.get('names') if isinstance(context, dict) else None
    return isinstance(names, dict) and any(
        _display_key(value) == _display_key(name) for name in names.values() if _text(name))


def _precise_translation(value, original, location, registry):
    if value and _broad_name(value, location, registry) and not _broad_name(original, location, registry):
        return ''
    return value


def document_endpoint(listing, side, language, registry):
    """Return a complete saved endpoint, retaining unknown/custom text verbatim."""
    language = 'ka' if language in ('ge', 'ka') else 'ru'
    raw = _text(getattr(listing, side + '_city', None)) or '—'
    location = getattr(listing, side + '_location', None)
    if not isinstance(location, dict):
        return _known_name(raw, registry, language, getattr(listing, side + '_city_id', None))

    label = _text(location.get('label')) or raw
    address = _text(location.get('address')) or _text(getattr(listing, side + '_address', None))
    custom = location.get('label_mode') == 'custom'
    translated_label = _localized(location, language, 'label')
    translated_address = _localized(location, language, 'address')
    if location.get('kind') == 'point':
        translated_label = _precise_translation(translated_label, label, location, registry)
        translated_address = _precise_translation(translated_address, address, location, registry)
        # An automatic label can itself be the full street address. A saved
        # full localized address replaces that duplicate, never a city lookup.
        if not custom and translated_address and _display_key(label) == _display_key(address):
            return translated_address
        shown_label = label if custom else translated_label or label
        shown_address = translated_address or address
    else:
        shown_label = label if custom else (translated_label or _text(location.get(
            'name_ge' if language == 'ka' else 'name_ru')) or _known_name(label, registry, language))
        shown_address = translated_address or _known_name(address, registry, language)

    if not shown_address or _display_key(shown_label) == _display_key(shown_address):
        return shown_label
    if not custom and _display_key(shown_label) in {
            _display_key(component) for component in shown_address.split(',')}:
        return shown_address
    return shown_label + ', ' + shown_address


def act_route_renderer(listing, registry, generate_pdf):
    """Freeze both locale labels in the PDFs without changing payload v1.

    Only first issuance calls this adapter. Existing archives are returned as
    their original bytes; their payload, CSV snapshot and schema stay intact.
    """
    labels = {language: {side + '_city': document_endpoint(listing, side, language, registry)
                         for side in ('from', 'to')} for language in ('ru', 'ge')}

    def render(data):
        return generate_pdf({**data, **labels[data['lang']]})

    return render
