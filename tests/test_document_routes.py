"""Document locale display and old act byte compatibility; no providers."""
from copy import deepcopy
from datetime import datetime, timezone
import io
from types import SimpleNamespace
from unittest.mock import Mock

from pypdf import PdfReader
import pytest

from app.models.deal import Deal
from app.models.deal_act_archive import DealActArchive
from app.models.load import Load
from app.models.transport_offer import TransportOffer
from app.models.user import User
from app.routers import deals
from app.services.city_identity import CityRegistry
from app.services.deal_act_archive import create_bundle
from app.services.document_routes import document_endpoint
from tests.test_deal_completion_http import complete
from tests.test_document_requisites import documents, confirm_names, NAMES  # noqa: F401
from tests.test_publication_journeys import journey  # noqa: F401


def listing(label, location=None):
    return SimpleNamespace(from_city=label, from_city_id=None, from_location=location)


@pytest.mark.parametrize('alias', ['Тбилиси', 'Tbilisi', 'თბილისი'])
def test_only_complete_known_city_aliases_have_locale_names(alias):
    registry = CityRegistry()
    source = listing(alias)
    assert document_endpoint(source, 'from', 'ru', registry) == 'Тбилиси'
    assert document_endpoint(source, 'from', 'ge', registry) == 'თბილისი'


@pytest.mark.parametrize('text', [
    'Тбилиси, улица Серго Закариадзе, 5', 'Склад «Тбилиси», въезд 7', 'Дарьяльский монастырь',
])
def test_unknown_legacy_postal_or_poi_text_is_not_replaced_by_a_city(text):
    for language in ('ru', 'ge'):
        assert document_endpoint(listing(text), 'from', language, CityRegistry()) == text


def test_saved_localized_poi_and_full_address_are_both_retained_without_mutation():
    location = {
        'kind': 'point', 'label_mode': 'auto', 'label': 'Дарьяльский монастырь',
        'address': 'Дарьяльское ущелье, вход 7', 'settlement_key': 'ge:stepantsminda',
        'localized': {'ka': {'label': 'დარიალის მონასტერი', 'address': 'დარიალის ხეობა, შესასვლელი 7'}},
    }
    before = deepcopy(location)
    source = listing('Степанцминда', location)
    assert document_endpoint(source, 'from', 'ru', CityRegistry()) == 'Дарьяльский монастырь, Дарьяльское ущелье, вход 7'
    assert document_endpoint(source, 'from', 'ge', CityRegistry()) == 'დარიალის მონასტერი, დარიალის ხეობა, შესასვლელი 7'
    assert location == before


def test_custom_poi_name_is_not_translated_but_saved_full_address_can_be_localized():
    source = listing('Тбилиси', {
        'kind': 'point', 'label_mode': 'custom', 'label': 'Склад №7',
        'address': 'Тбилиси, улица Серго Закариадзе, 5',
        'localized': {'ka': {'label': 'Не подменять авторское название',
                             'address': 'თბილისი, სერგო ზაქარიაძის ქუჩა, 5'}},
    })
    assert document_endpoint(source, 'from', 'ge', CityRegistry()) == 'Склад №7, თბილისი, სერგო ზაქარიაძის ქუჩა, 5'


@pytest.mark.parametrize('label,address', [
    ('Склад 1', 'Тбилиси, Склад 10, въезд 7'),
    ('Бар', 'Тбилиси, улица Бараташвили, 7'),
])
def test_distinct_poi_name_is_not_lost_when_it_is_a_substring_of_the_address(label, address):
    source = listing('Тбилиси', {
        'kind': 'point', 'label_mode': 'auto', 'label': label, 'address': address,
    })
    for language in ('ru', 'ge'):
        assert document_endpoint(source, 'from', language, CityRegistry()) == label + ', ' + address


@pytest.mark.parametrize('saved_address,expected', [
    ('თბილისი', 'Тбилиси, улица Серго Закариадзе, 5'),
    ('თბილისი, სერგო ზაქარიაძის ქუჩა, 5', 'თბილისი, სერგო ზაქარიაძის ქუჩა, 5'),
])
def test_city_only_presentation_never_replaces_the_street_pin(saved_address, expected):
    source = listing('Тбилиси', {
        'kind': 'point', 'label_mode': 'auto',
        'label': 'Тбилиси, улица Серго Закариадзе, 5',
        'address': 'Тбилиси, улица Серго Закариадзе, 5', 'settlement_key': 'ge:tbilisi',
        'localized': {'ka': {'label': 'თბილისი', 'address': saved_address}},
        'context': {'relation': 'within', 'names': {'ru': 'Тбилиси', 'ka': 'თბილისი'}},
    })
    assert document_endpoint(source, 'from', 'ge', CityRegistry()) == expected


async def download(context, deal_id, language):
    return await context['client'].get(f'/api/deals/{deal_id}/act.pdf', params={'lang': language},
                                       headers=context['headers']['shipper'])


def pdf_text(content):
    return '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(content)).pages)


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['cargo', 'transport'])
@pytest.mark.parametrize('first_language', ['ru', 'ge'])
async def test_new_acts_have_both_locale_routes_and_never_relocalize_after_issue(documents, source, first_language, monkeypatch):
    deal_id, _ = await complete(documents, source)
    await confirm_names(documents)
    first = await download(documents, deal_id, first_language)
    assert first.status_code == 200, first.text
    original = {language: await download(documents, deal_id, language) for language in ('ru', 'ge')}
    assert 'Тбилиси → Батуми' in pdf_text(original['ru'].content)
    assert 'თბილისი → ბათუმი' in pdf_text(original['ge'].content)
    for response in original.values():
        assert response.status_code == 200
        for name in NAMES.values():
            assert name in pdf_text(response.content)
    async with documents['sessions']() as db:
        archive = await db.get(DealActArchive, deal_id)
        frozen_hash = archive.payload_sha256
        assert archive.schema_version == 1
        assert set(archive.payload) == {'document', 'truck_labels', 'accounting'}
        assert archive.payload['document']['from_city'] == 'Тбилиси'
        deal = await db.get(Deal, deal_id)
        route = await db.get(Load, deal.load_id) if deal.load_id else await db.get(TransportOffer, deal.transport_offer_id)
        route.from_city = 'Changed source'; route.to_city = 'Changed destination'
        await db.commit()
    monkeypatch.setattr('app.services.document_routes.document_endpoint', Mock(side_effect=AssertionError('Issued acts must not be localized again')))
    monkeypatch.setattr(deals, 'generate_act_pdf', Mock(side_effect=AssertionError('Issued acts must not be rendered again')))
    for language in ('ru', 'ge'):
        again = await download(documents, deal_id, language)
        assert again.status_code == 200
        assert again.content == original[language].content
    async with documents['sessions']() as db:
        assert (await db.get(DealActArchive, deal_id)).payload_sha256 == frozen_hash


@pytest.mark.asyncio
async def test_preexisting_v1_act_keeps_its_original_russian_route_even_in_ge_pdf(documents, monkeypatch):
    deal_id, _ = await complete(documents, 'cargo')
    await confirm_names(documents)
    async with documents['sessions']() as db:
        deal = await db.get(Deal, deal_id)
        shipper = await db.get(User, deal.shipper_id); carrier = await db.get(User, deal.carrier_id)
        load = await db.get(Load, deal.load_id)
        issued_at = datetime.now(timezone.utc)
        payload = deals._act_payload(deal, shipper, carrier, load, None, None, NAMES, issued_at)
        legacy = create_bundle(deal_id, payload, issued_at, deals.generate_act_pdf)
        before = {'ru': legacy.ru_pdf, 'ge': legacy.ge_pdf}
        assert 'Тбилиси → Батуми' in pdf_text(before['ge'])
        db.add(legacy); await db.commit()
    monkeypatch.setattr('app.services.document_routes.document_endpoint', Mock(side_effect=AssertionError('Do not repair old act routes')))
    monkeypatch.setattr(deals, 'generate_act_pdf', Mock(side_effect=AssertionError('Do not regenerate old acts')))
    for language in ('ru', 'ge'):
        response = await download(documents, deal_id, language)
        assert response.status_code == 200
        assert response.content == before[language]
