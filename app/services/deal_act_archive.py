"""Versioned act bundles. Never repair, re-render or overwrite an issued act.

Hashes detect accidental corruption, not a database administrator able to rewrite
both documents and hashes. Archived private data is returned only by participant
routes; list responses expose issuance metadata alone.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from hmac import compare_digest
import json
import re

from fastapi import HTTPException

from app.models.deal_act_archive import DealActArchive

DOCUMENT_FIELDS = frozenset({
    'act_number', 'deal_id', 'created_at', 'completed_at', 'shipper_name', 'shipper_inn', 'shipper_phone',
    'carrier_name', 'carrier_inn', 'carrier_phone', 'from_city', 'to_city', 'cargo_desc',
    'weight_kg', 'agreed_price', 'currency', 'loading_at', 'delivered_at', 'generated_at',
})
ACCOUNTING_FIELDS = frozenset({
    'act_number', 'date', 'shipper', 'shipper_inn', 'carrier', 'carrier_inn', 'from_city',
    'to_city', 'cargo_desc', 'weight_kg', 'amount', 'currency', 'payment_type', 'deal_id',
    'deal_source', 'load_id', 'transport_offer_id', 'loading_date', 'delivery_date',
})
MAX_PDF_BYTES = 20 * 1024 * 1024


def unavailable():
    return HTTPException(500, {
        'code': 'document_archive_unavailable',
        'message_ru': 'Сохранённый акт временно недоступен. Обратитесь в поддержку; документ не будет перезаписан.',
        'message_ge': 'შენახული აქტი დროებით მიუწვდომელია. დაუკავშირდით მხარდაჭერას; დოკუმენტი არ გადაიწერება.',
    })


def utc_iso(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _json_default(value):
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError('Unsupported archive value')


def canonical_payload(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=_json_default).encode('utf-8')


def _digest_matches(content, digest):
    return (isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest) is not None
            and compare_digest(sha256(content).hexdigest(), digest))


def metadata(archive):
    if archive is None:
        return {'issued': False, 'issued_at': None}
    # Listing a cabinet is not an integrity check and must not read PDF blobs.
    return {'issued': True, 'issued_at': utc_iso(archive.issued_at) if isinstance(archive.issued_at, datetime) else None}


def validate_payload(archive, deal_id):
    """CSV validates its frozen payload without fetching either large PDF blob."""
    try:
        if archive.schema_version != 1 or not isinstance(archive.issued_at, datetime):
            raise ValueError('Unsupported archive version or timestamp')
        payload = archive.payload
        if archive.deal_id != deal_id or not _digest_matches(canonical_payload(payload), archive.payload_sha256):
            raise ValueError('Archive integrity mismatch')
        if (not isinstance(payload, dict) or set(payload) != {'document', 'truck_labels', 'accounting'}
                or not isinstance(payload['document'], dict) or set(payload['document']) != DOCUMENT_FIELDS
                or not isinstance(payload['accounting'], dict) or set(payload['accounting']) != ACCOUNTING_FIELDS
                or not isinstance(payload['truck_labels'], dict) or set(payload['truck_labels']) != {'ru', 'ge'}):
            raise ValueError('Unsupported archive schema')
        document, accounting = payload['document'], payload['accounting']
        if document['deal_id'] != deal_id or accounting['deal_id'] != deal_id:
            raise ValueError('Archive identity mismatch')
        if document['generated_at'] != utc_iso(archive.issued_at):
            raise ValueError('Archive issuance time mismatch')
        for key in ('created_at', 'completed_at', 'loading_at', 'delivered_at'):
            if document[key] is not None:
                if not isinstance(document[key], str):
                    raise ValueError('Invalid archived date')
                datetime.fromisoformat(document[key])
        for key in ('act_number', 'shipper_inn', 'shipper_phone', 'carrier_inn', 'carrier_phone',
                    'from_city', 'to_city', 'currency'):
            if not isinstance(document[key], str):
                raise ValueError('Invalid archived text')
        if not all(isinstance(value, str) for value in payload['truck_labels'].values()):
            raise ValueError('Invalid archived truck labels')
        for role in ('shipper', 'carrier'):
            if (not isinstance(document[role + '_name'], str) or not document[role + '_name']
                    or accounting[role] != document[role + '_name']
                    or accounting[role + '_inn'] != document[role + '_inn']):
                raise ValueError('Archive party mismatch')
        if (accounting['act_number'] != document['act_number']
                or accounting['from_city'] != document['from_city']
                or accounting['to_city'] != document['to_city']
                or accounting['currency'] != document['currency']
                or accounting['cargo_desc'] != document['cargo_desc']
                or accounting['weight_kg'] != document['weight_kg']
                or Decimal(str(accounting['amount'])) != Decimal(str(document['agreed_price']))
                or not Decimal(str(accounting['amount'])).is_finite()):
            raise ValueError('Archive accounting mismatch')
        return payload
    except HTTPException:
        raise
    except Exception:
        raise unavailable() from None


def validate_bundle(archive, deal_id):
    payload = validate_payload(archive, deal_id)
    for language in ('ru', 'ge'):
        content = getattr(archive, language + '_pdf')
        if (not isinstance(content, bytes) or not 5 < len(content) <= MAX_PDF_BYTES
                or not content.startswith(b'%PDF-') or not content.rstrip().endswith(b'%%EOF')
                or not _digest_matches(content, getattr(archive, language + '_sha256'))):
            raise unavailable()
    return payload


def create_bundle(deal_id, payload, issued_at, generate_pdf):
    """Render both languages before inserting anything; caller owns the transaction."""
    try:
        payload_bytes = canonical_payload(payload)
        payload = json.loads(payload_bytes)
        archive = DealActArchive(deal_id=deal_id, schema_version=1, issued_at=issued_at,
                                 payload=payload, payload_sha256=sha256(payload_bytes).hexdigest())
        for language in ('ru', 'ge'):
            data = {**payload['document'], 'lang': language,
                    'truck_type': payload['truck_labels'][language],
                    'agreed_price': Decimal(str(payload['document']['agreed_price']))}
            content = generate_pdf(data)
            setattr(archive, language + '_pdf', content)
            setattr(archive, language + '_sha256', sha256(content).hexdigest())
        validate_bundle(archive, deal_id)
        return archive
    except HTTPException:
        raise
    except Exception:
        raise unavailable() from None
