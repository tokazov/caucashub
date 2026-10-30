"""Private owner-attested Georgian party names; never derived from display aliases."""
from datetime import datetime, timezone
import re
import unicodedata

from fastapi import HTTPException


def normalize_legal_name(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Укажите грузинское наименование для документов / მიუთითეთ ქართული დასახელება')
    if any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('Наименование не должно содержать управляющие символы / დაუშვებელია საკონტროლო სიმბოლოები')
    value = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()
    if not value:
        return None
    allowed = set(' 0123456789\'"„“”«»‘’().,-–—')
    letters = 0
    for char in value:
        if unicodedata.category(char).startswith('L') and unicodedata.name(char, '').startswith('GEORGIAN'):
            letters += 1
        elif char not in allowed:
            raise ValueError('Используйте грузинские буквы для наименования / გამოიყენეთ ქართული ასოები')
    if letters < 2 or len(value) > 255:
        raise ValueError('Нужно не менее двух грузинских букв, максимум 255 символов / მინიმუმ ორი ქართული ასო, მაქსიმუმ 255 სიმბოლო')
    return value


def confirmed_name(user):
    if user is None or getattr(user, 'is_deleted', False) or not getattr(user, 'legal_name_ka_confirmed_at', None):
        return None
    try:
        return normalize_legal_name(getattr(user, 'legal_name_ka', None))
    except ValueError:
        return None


def private_name_fields(user):
    return {'legal_name_ka': getattr(user, 'legal_name_ka', None),
            'legal_name_ka_confirmed': confirmed_name(user) is not None}


def apply_name_update(user, data):
    fields = data.model_fields_set
    has_name = 'legal_name_ka' in fields
    has_confirmation = 'legal_name_ka_confirmed' in fields
    if not has_name and not has_confirmation:
        return
    name = data.legal_name_ka if has_name else getattr(user, 'legal_name_ka', None)
    if has_name and name is None:
        user.legal_name_ka = None
        user.legal_name_ka_confirmed_at = None
        return
    changed = has_name and name != getattr(user, 'legal_name_ka', None)
    if changed and not (has_confirmation and data.legal_name_ka_confirmed is True):
        raise ValueError('Подтвердите точное грузинское наименование / დაადასტურეთ ზუსტი ქართული დასახელება')
    if has_confirmation and data.legal_name_ka_confirmed is True:
        name = normalize_legal_name(name)
        if name is None:
            raise ValueError('Сначала укажите грузинское наименование / ჯერ მიუთითეთ ქართული დასახელება')
        if changed or not getattr(user, 'legal_name_ka_confirmed_at', None):
            user.legal_name_ka_confirmed_at = datetime.now(timezone.utc)
    elif has_confirmation:
        user.legal_name_ka_confirmed_at = None
    if has_name:
        user.legal_name_ka = name


def document_readiness(shipper, carrier, viewer_id):
    missing = [{'role': role, 'is_current_user': bool(user and user.id == viewer_id)}
               for role, user in (('shipper', shipper), ('carrier', carrier)) if confirmed_name(user) is None]
    return {'ready': not missing, 'missing_parties': missing}


def require_document_names(shipper, carrier, viewer_id):
    readiness = document_readiness(shipper, carrier, viewer_id)
    if not readiness['ready']:
        raise_missing_names(readiness['missing_parties'])
    return {'shipper': confirmed_name(shipper), 'carrier': confirmed_name(carrier)}


def raise_missing_names(missing):
    raise HTTPException(409, {
        'code': 'document_requisites_required',
        'message_ru': 'Для документа обе стороны должны указать и подтвердить грузинское наименование.',
        'message_ge': 'დოკუმენტისთვის ორივე მხარემ უნდა მიუთითოს და დაადასტუროს ქართული დასახელება.',
        'missing_parties': missing,
    })
