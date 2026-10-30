"""Real authenticated act issuance on disposable SQLite/PostgreSQL only."""
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.models.deal import Deal, DealStatus
from app.models.deal_act_archive import DealActArchive
from app.models.load import Load
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.user import User
from app.routers import deals
from app.services.deal_act_archive import canonical_payload, metadata, validate_bundle, validate_payload
from tests.test_publication_journeys import journey  # noqa: F401
from tests.test_document_requisites import documents, confirm_names, NAMES, save  # noqa: F401
from tests.test_deal_completion_http import accepted_deal, complete, outsider


async def act(context, deal_id, lang='ru', role='shipper'):
    return await context['client'].get(f'/api/deals/{deal_id}/act.pdf', params={'lang':lang},
                                       headers=context['headers'][role])


async def archive_count(context):
    async with context['sessions']() as db:
        return (await db.execute(select(func.count()).select_from(DealActArchive))).scalar_one()


async def csv_rows(context, **params):
    response=await context['client'].get('/api/deals/export',params={'format':'csv',**params},
                                        headers=context['headers']['shipper'])
    assert response.status_code==200,response.text
    return [row for row in csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';')
            if str(row.get('deal_id','')).isdigit()]


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['cargo','transport'])
async def test_first_issue_keeps_both_exact_pdfs_and_frozen_accounting_after_every_source_changes(documents,source,monkeypatch):
    deal_id,_=await complete(documents,source);await confirm_names(documents)
    renderer=Mock(wraps=deals.generate_act_pdf);monkeypatch.setattr(deals,'generate_act_pdf',renderer)
    original={language:await act(documents,deal_id,language) for language in ('ru','ge')}
    assert all(response.status_code==200 for response in original.values())
    assert renderer.call_count==2  # Both languages rendered exactly once, at the first issue.
    first_rows=await csv_rows(documents)
    async with documents['sessions']() as db:
        record=await db.get(DealActArchive,deal_id)
        assert record and record.schema_version==1
        assert set(record.payload)=={'document','truck_labels','accounting'}
        assert 'email' not in str(record.payload)
        issued_at=metadata(record)['issued_at']
        for language,response in original.items():
            assert response.content==getattr(record,language+'_pdf')
            assert sha256(response.content).hexdigest()==getattr(record,language+'_sha256')
            assert response.headers['x-act-issued-at']==issued_at
        assert record.payload_sha256==sha256(canonical_payload(record.payload)).hexdigest()
        frozen_period=record.payload['document']['completed_at'][:10]
    # Owners can edit their profiles; this never edits a previously issued act.
    for role in ('shipper','carrier'):
        changed=await save(documents,role,legal_name_ka='შპს ახალი სახელი',legal_name_ka_confirmed=True,inn='404987654')
        assert changed.status_code==200,changed.text
    async with documents['sessions']() as db:
        deal=await db.get(Deal,deal_id)
        route=await db.get(Load,deal.load_id) if deal.load_id else await db.get(TransportOffer,deal.transport_offer_id)
        route.from_city='Changed source';route.to_city='Changed destination';route.truck_type='bort'
        if source=='cargo':route.cargo_desc='Changed cargo';route.weight_kg=9999
        deal.agreed_price=1234;deal.currency='USD';deal.act_number='CH-2099-CHANGED'
        deal.completed_at=datetime.now(timezone.utc)+timedelta(days=90)
        deal.loading_at=datetime.now(timezone.utc)+timedelta(days=80)
        await db.execute(update(User).values(phone='+995599999999'))
        await db.commit()
    monkeypatch.setattr(deals,'generate_act_pdf',Mock(side_effect=AssertionError('Issued acts must not render again')))
    for language in ('ru','ge'):
        again=await act(documents,deal_id,language,role='carrier')
        assert again.status_code==200,again.text
        assert again.content==original[language].content
        assert again.headers['x-act-issued-at']==issued_at
        assert 'CH-2099-CHANGED' not in again.headers['content-disposition']
    assert await csv_rows(documents)==first_rows
    assert await csv_rows(documents,**{'from':frozen_period,'to':frozen_period})==first_rows
    assert await archive_count(documents)==1


@pytest.mark.asyncio
async def test_revoke_and_soft_delete_do_not_rewrite_issued_act_but_new_acts_still_require_names(documents):
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    before=await act(documents,deal_id);assert before.status_code==200
    assert (await save(documents,'carrier',legal_name_ka_confirmed=False)).status_code==200
    assert (await act(documents,deal_id)).content==before.content
    assert (await csv_rows(documents))[0]['carrier']==NAMES['carrier']
    for endpoint in ('/api/deals/my','/api/deals/export?format=json'):
        response=await documents['client'].get(endpoint,headers=documents['headers']['shipper'])
        assert response.status_code==200
        row=response.json()['deals'][0]
        assert row['document_readiness']=={'ready':True,'missing_parties':[]}
        assert row['document_archive']['issued'] is True and row['document_archive']['issued_at']
        assert NAMES['shipper'] not in response.text and NAMES['carrier'] not in response.text
        assert 'ru_pdf' not in response.text and 'payload_sha256' not in response.text
    fresh,_=await complete(documents,'transport')
    assert (await act(documents,fresh)).status_code==409
    assert await archive_count(documents)==1
    # Financial history is private to the remaining live participant; the deleted
    # participant's old token is still rejected by normal authentication.
    async with documents['sessions']() as db:
        carrier=(await db.execute(select(User).where(User.email=='carrier@example.test'))).scalar_one()
        carrier.is_deleted=True;carrier.is_active=False;carrier.legal_name_ka=None
        carrier.legal_name_ka_confirmed_at=None;carrier.inn=None;carrier.phone=None
        await db.commit()
    assert (await act(documents,deal_id)).content==before.content
    assert (await act(documents,deal_id,role='carrier')).status_code in (401,403)


@pytest.mark.asyncio
async def test_csv_and_lists_never_issue_an_act_and_unauthorized_reads_never_create_one(documents):
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    assert (await csv_rows(documents))[0]['shipper']==NAMES['shipper']
    listing=await documents['client'].get('/api/deals/my',headers=documents['headers']['shipper'])
    assert listing.json()['deals'][0]['document_archive']=={'issued':False,'issued_at':None}
    headers=await outsider(documents)
    response=await documents['client'].get(f'/api/deals/{deal_id}/act.pdf',headers=headers)
    assert response.status_code==403
    pending=await accepted_deal(documents,'transport')
    assert (await act(documents,pending)).status_code==400
    async with documents['sessions']() as db:
        deal=await db.get(Deal,pending);deal.status=DealStatus.completed;deal.shipper_confirmed=True
        deal.carrier_confirmed=False;await db.commit()
    assert (await act(documents,pending)).status_code==400
    assert await archive_count(documents)==0


@pytest.mark.asyncio
async def test_second_language_render_failure_is_atomic_and_recoverable_without_overwriting_anything(documents,monkeypatch):
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    real_renderer=deals.generate_act_pdf
    def failing(data):
        if data['lang']=='ge':raise RuntimeError('Synthetic renderer failure')
        return real_renderer(data)
    monkeypatch.setattr(deals,'generate_act_pdf',failing)
    response=await act(documents,deal_id)
    assert response.status_code==500 and response.json()['detail']['code']=='document_archive_unavailable'
    assert await archive_count(documents)==0
    monkeypatch.setattr(deals,'generate_act_pdf',real_renderer)
    assert (await act(documents,deal_id,'ge')).status_code==200
    assert await archive_count(documents)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('field',['ru_pdf','ge_pdf','ru_sha256','ge_sha256','payload','payload_sha256'])
async def test_corruption_fails_closed_without_repair_or_public_payload_leaks(documents,monkeypatch,field):
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    assert (await act(documents,deal_id)).status_code==200
    async with documents['sessions']() as db:
        record=await db.get(DealActArchive,deal_id)
        if field.endswith('_pdf'):value=b'%PDF-1.4\nCORRUPTED\n%%EOF\n'
        elif field.endswith('_sha256'):value='0'*64
        else:
            value=deepcopy(record.payload);value['accounting']['shipper']='CORRUPTED PRIVATE VALUE'
        await db.execute(update(DealActArchive).where(DealActArchive.deal_id==deal_id).values(**{field:value}))
        await db.commit()
    renderer=Mock(side_effect=AssertionError('Corrupt archive must not regenerate'))
    monkeypatch.setattr(deals,'generate_act_pdf',renderer)
    response=await act(documents,deal_id)
    assert response.status_code==500
    assert response.json()['detail']['code']=='document_archive_unavailable'
    assert 'PRIVATE VALUE' not in response.text and NAMES['shipper'] not in response.text
    renderer.assert_not_called();assert await archive_count(documents)==1
    for endpoint in ('/api/deals/my','/api/deals/export?format=json'):
        result=await documents['client'].get(endpoint,headers=documents['headers']['shipper'])
        assert result.status_code==200
        assert result.json()['deals'][0]['document_archive']['issued'] is True
        assert 'PRIVATE VALUE' not in result.text and NAMES['shipper'] not in result.text
    if field in ('payload','payload_sha256'):
        result=await documents['client'].get('/api/deals/export?format=csv',headers=documents['headers']['shipper'])
        assert result.status_code==500 and result.json()['detail']['code']=='document_archive_unavailable'
    headers=await outsider(documents)
    assert (await documents['client'].get(f'/api/deals/{deal_id}/act.pdf',headers=headers)).status_code==403


def test_unknown_archive_version_does_not_break_list_but_cannot_be_downloaded():
    record=SimpleNamespace(schema_version=2,issued_at=datetime.now(timezone.utc),deal_id=1)
    assert metadata(record)['issued'] is True
    with pytest.raises(HTTPException) as error:validate_payload(record,1)
    assert error.value.status_code==500


def test_fresh_missing_archive_metadata_is_explicit():
    assert metadata(None)=={'issued':False,'issued_at':None}


@pytest.mark.asyncio
@pytest.mark.parametrize('request_state',['accepted','missing_request','missing_weight'])
async def test_unissued_transport_export_uses_accepted_cargo_not_vehicle_capacity_without_issuing(documents,request_state):
    deal_id,_=await complete(documents,'transport');await confirm_names(documents)
    async with documents['sessions']() as db:
        deal=await db.get(Deal,deal_id)
        offer=await db.get(TransportOffer,deal.transport_offer_id)
        request=await db.get(TransportRequest,deal.transport_request_id)
        assert offer.capacity_kg!=request.weight_kg and offer.notes!=request.cargo_description
        if request_state=='missing_request':deal.transport_request_id=None
        elif request_state=='missing_weight':request.weight_kg=None
        await db.commit()
    before=(await csv_rows(documents))[0]
    assert await archive_count(documents)==0
    assert before['cargo_desc']==('—' if request_state=='missing_request' else 'HTTP completion cargo: книги, მადლობა')
    assert before['weight_kg']==('3000.0' if request_state=='accepted' else '—')
    assert 'Offer note' not in before['cargo_desc'] and before['weight_kg']!='10000.0'
    response=await act(documents,deal_id)
    assert response.status_code==200,response.text
    async with documents['sessions']() as db:
        captured=(await db.get(DealActArchive,deal_id)).payload['document']
        assert before['cargo_desc']==captured['cargo_desc']
        assert before['weight_kg']==str(captured['weight_kg'])
    assert (await csv_rows(documents))[0]==before


@pytest.mark.asyncio
@pytest.mark.parametrize('commit_state',['before_commit','after_commit','rollback_failure',
                                        'integrity_before_commit','integrity_rollback_failure'])
async def test_database_error_parameters_are_sanitized_and_uncertain_commit_never_reissues(documents,monkeypatch,commit_state):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.exc import IntegrityError, OperationalError
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    original_commit=AsyncSession.commit
    async def failing_commit(session):
        if commit_state=='after_commit':
            await original_commit(session)
        else:
            await session.flush()
        error_type=IntegrityError if commit_state.startswith('integrity_') else OperationalError
        raise error_type('INSERT INTO deal_act_archives ...',
                         {'private_payload':'ARCHIVE-PARAM-CANARY-95'}, RuntimeError('Synthetic connection failure'))
    with monkeypatch.context() as context:
        context.setattr(AsyncSession,'commit',failing_commit)
        if commit_state.endswith('rollback_failure'):
            async def failed_rollback(session):
                raise OperationalError('ROLLBACK',{'private_payload':'ARCHIVE-PARAM-CANARY-95'},RuntimeError('Synthetic broken connection'))
            context.setattr(AsyncSession,'rollback',failed_rollback)
        response=await act(documents,deal_id)
    assert response.status_code==500
    assert response.json()['detail']['code']=='document_archive_unavailable'
    assert 'ARCHIVE-PARAM-CANARY-95' not in response.text and 'INSERT INTO' not in response.text
    assert await archive_count(documents)==(1 if commit_state=='after_commit' else 0)
    if commit_state=='after_commit':
        async with documents['sessions']() as db:
            original=(await db.get(DealActArchive,deal_id)).ru_pdf
        monkeypatch.setattr(deals,'generate_act_pdf',Mock(side_effect=AssertionError('Uncertain commit must not reissue')))
    retry=await act(documents,deal_id)
    assert retry.status_code==200,retry.text
    if commit_state=='after_commit':assert retry.content==original
    assert await archive_count(documents)==1


@pytest.mark.asyncio
async def test_missing_requisites_response_survives_failed_cleanup_without_sql_parameters(documents,monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.exc import OperationalError
    deal_id,_=await complete(documents,'cargo')
    async def failed_rollback(session):
        raise OperationalError('ROLLBACK',{'private_payload':'ARCHIVE-PARAM-CANARY-95'},RuntimeError('Synthetic broken connection'))
    with monkeypatch.context() as context:
        context.setattr(AsyncSession,'rollback',failed_rollback)
        response=await act(documents,deal_id)
    assert response.status_code==409
    assert response.json()['detail']['code']=='document_requisites_required'
    assert 'ARCHIVE-PARAM-CANARY-95' not in response.text and 'ROLLBACK' not in response.text
    assert await archive_count(documents)==0


@pytest.mark.asyncio
async def test_request_cancellation_survives_failed_cleanup_and_suppresses_sql_context(documents,monkeypatch):
    import asyncio
    from sqlalchemy.exc import OperationalError
    deal_id,_=await complete(documents,'cargo');await confirm_names(documents)
    async with documents['sessions']() as db:
        user=(await db.execute(select(User).where(User.email=='shipper@example.test'))).scalar_one()
        async def failed_rollback():
            raise OperationalError('ROLLBACK',{'private_payload':'ARCHIVE-PARAM-CANARY-95'},RuntimeError('Synthetic broken connection'))
        monkeypatch.setattr(db,'rollback',failed_rollback)
        monkeypatch.setattr(deals,'create_bundle',Mock(side_effect=asyncio.CancelledError('Synthetic cancelled request')))
        with pytest.raises(asyncio.CancelledError) as result:
            await deals.download_act(deal_id,lang='ru',db=db,current_user=user)
        assert str(result.value)=='Synthetic cancelled request'
        assert result.value.__suppress_context__ is True
    assert await archive_count(documents)==0
