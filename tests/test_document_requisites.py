"""Private owner-entered document names; real HTTP on disposable databases."""
import csv
from datetime import datetime, timedelta, timezone
import io
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from pypdf import PdfReader
from sqlalchemy import select

from app.models.deal import Deal, DealStatus
from app.models.user import User
from app.routers import deals, users
from app.services.document_names import normalize_legal_name
from tests.test_publication_journeys import journey  # noqa: F401
from tests.test_deal_completion_http import accepted_deal, complete, outsider


NAMES={'shipper':'შპს ქართული ტვირთი','carrier':'შპს ქართული ტრანსპორტი'}


@pytest.mark.parametrize('bad',['Test carrier','ООО Груз','შპს Cargo','შპს Груз','ა','1234',
                                'შპს\x00სახელი','შპს\nსახელი','შპს\tსახელი','შპს\u200bსახელი','შპს\u202eსახელი',
                                'შპს🙂სახელი','ა'*256])
def test_name_rejects_other_scripts_controls_and_invalid_lengths(bad):
    with pytest.raises(ValueError):normalize_legal_name(bad)


@pytest.mark.parametrize('raw,normalized',[(None,None),('    ',None),
    ('  შპს   „ქართული-ტვირთი“ (123)  ','შპს „ქართული-ტვირთი“ (123)'),
    ('შპს\u00a0ქართული','შპს ქართული'),('ᲨᲞᲡ ᲥᲐᲠᲗᲣᲚᲘ','ᲨᲞᲡ ᲥᲐᲠᲗᲣᲚᲘ')])
def test_georgian_spelling_is_normalized_without_transliteration_or_case_change(raw,normalized):
    assert normalize_legal_name(raw)==normalized


@pytest_asyncio.fixture
async def documents(journey,monkeypatch):
    journey['client']._transport.app.include_router(users.router,prefix='/api/users')
    monkeypatch.setattr(deals,'_send_completed_emails',Mock(return_value=None))
    monkeypatch.setattr(users,'_send_deletion_email',AsyncMock())
    return journey


async def save(context,role='shipper',**body):
    return await context['client'].put('/api/users/me',headers=context['headers'][role],json=body)


async def confirm_names(context):
    for role,name in NAMES.items():
        response=await save(context,role,legal_name_ka=name,legal_name_ka_confirmed=True)
        assert response.status_code==200,response.text


@pytest.mark.asyncio
async def test_profile_confirmation_is_explicit_private_persistent_and_atomic(documents):
    client=documents['client'];headers=documents['headers']['shipper']
    initial=(await client.get('/api/users/me',headers=headers)).json()
    assert initial['legal_name_ka'] is None and initial['legal_name_ka_confirmed'] is False
    forged_stamp=await save(documents,legal_name_ka_confirmed_at='2026-01-01T00:00:00Z')
    assert forged_stamp.status_code==200 and forged_stamp.json()['legal_name_ka_confirmed'] is False
    empty=await client.get('/api/deals/export?format=csv',headers=headers)
    assert empty.status_code==200 and 'Test shipper' not in empty.text
    for body in ({'legal_name_ka':NAMES['shipper'],'company_name':'Must not save'},
                 {'legal_name_ka':NAMES['shipper'],'legal_name_ka_confirmed':False},
                 {'legal_name_ka_confirmed':True},
                 {'legal_name_ka':NAMES['shipper'],'legal_name_ka_confirmed':'true'},
                 {'legal_name_ka':'შპს\nქართული','legal_name_ka_confirmed':True}):
        response=await save(documents,**body)
        assert response.status_code==422,response.text
    current=(await client.get('/api/users/me',headers=headers)).json()
    assert current['company_name']==initial['company_name'] and current['legal_name_ka'] is None
    good=await save(documents,legal_name_ka='  შპს   ქართული ტვირთი ',legal_name_ka_confirmed=True)
    assert good.status_code==200 and good.json()['legal_name_ka']==NAMES['shipper']
    async with documents['sessions']() as db:
        owner=(await db.execute(select(User).where(User.email=='shipper@example.test'))).scalar_one()
        stamp=owner.legal_name_ka_confirmed_at;owner_id=owner.id
        assert stamp is not None and owner.is_verified is not True
    assert (await save(documents,city='Tbilisi',lang='ge')).status_code==200
    rejected=await save(documents,legal_name_ka='შპს სხვა სახელი',company_name='Must not save')
    assert rejected.status_code==422
    login=await client.post('/api/auth/login',json={'email':'shipper@example.test','password':'JourneyTest39!'})
    me=await client.get('/api/users/me',headers={'Authorization':'Bearer '+login.json()['token']})
    assert me.json()['legal_name_ka']==NAMES['shipper'] and me.json()['legal_name_ka_confirmed'] is True
    async with documents['sessions']() as db:
        assert (await db.get(User,owner_id)).legal_name_ka_confirmed_at==stamp
    for endpoint in (f'/api/users/{owner_id}',f'/api/users/{owner_id}/profile'):
        public=await client.get(endpoint)
        assert public.status_code==200,public.text
        assert NAMES['shipper'] not in public.text and 'legal_name_ka' not in public.text
    assert (await save(documents,legal_name_ka_confirmed=False)).json()['legal_name_ka_confirmed'] is False
    assert (await save(documents,legal_name_ka_confirmed=True)).json()['legal_name_ka_confirmed'] is True
    assert (await save(documents,legal_name_ka=None)).json()['legal_name_ka'] is None
    assert (await save(documents,legal_name_ka_confirmed=True)).status_code==422
    assert (await save(documents,legal_name_ka=NAMES['shipper'],legal_name_ka_confirmed=True)).status_code==200
    cleared=await save(documents,legal_name_ka='   ',legal_name_ka_confirmed=True)
    assert cleared.status_code==200 and cleared.json()['legal_name_ka'] is None and cleared.json()['legal_name_ka_confirmed'] is False


@pytest.mark.asyncio
async def test_pdf_and_csv_gate_missing_parties_without_affecting_completion_or_json(documents):
    deal_id,_=await complete(documents,'cargo')
    client=documents['client'];headers=documents['headers']['shipper']
    for endpoint in (f'/api/deals/{deal_id}/act.pdf?lang=ru',f'/api/deals/{deal_id}/act.pdf?lang=ge',
                     '/api/deals/export?format=csv','/api/deals/export?format=anything'):
        response=await client.get(endpoint,headers=headers)
        assert response.status_code==409,response.text
        detail=response.json()['detail']
        assert detail['code']=='document_requisites_required' and detail['message_ru'] and detail['message_ge']
        assert detail['missing_parties']==[{'role':'shipper','is_current_user':True},{'role':'carrier','is_current_user':False}]
        assert all(set(item)=={'role','is_current_user'} for item in detail['missing_parties'])
    assert (await save(documents,legal_name_ka=NAMES['shipper'],legal_name_ka_confirmed=True)).status_code==200
    response=await client.get(f'/api/deals/{deal_id}/act.pdf',headers=headers)
    assert response.json()['detail']['missing_parties']==[{'role':'carrier','is_current_user':False}]
    for endpoint in ('/api/deals/my','/api/deals/export?format=json'):
        response=await client.get(endpoint,headers=headers)
        assert response.status_code==200,response.text
        row=response.json()['deals'][0]
        assert row['document_readiness']=={'ready':False,'missing_parties':[{'role':'carrier','is_current_user':False}]}
        assert NAMES['shipper'] not in response.text
    # Another participant's setting can never be written through PUT/me.
    await client.put('/api/users/me',headers=documents['headers']['carrier'],json={'id':99999,'legal_name_ka':NAMES['carrier'],'legal_name_ka_confirmed':True})
    assert (await client.get(f'/api/deals/{deal_id}/act.pdf',headers=headers)).status_code==200


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['cargo','transport'])
async def test_both_confirmed_names_are_used_for_pdf_and_signatures_in_every_ui_language(documents,source):
    deal_id,_=await complete(documents,source)
    await confirm_names(documents)
    client=documents['client'];headers=documents['headers']['shipper']
    for lang in ('ru','ge'):
        response=await client.get(f'/api/deals/{deal_id}/act.pdf',params={'lang':lang},headers=headers)
        assert response.status_code==200,response.text
        text='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
        for name in NAMES.values():assert text.count(name)>=2,text
        assert 'Test shipper' not in text and 'Test carrier' not in text
    csv_result=await client.get('/api/deals/export?format=csv',headers=headers)
    assert csv_result.status_code==200,csv_result.text
    rows=list(csv.DictReader(io.StringIO(csv_result.content.decode('utf-8-sig')),delimiter=';'))
    assert rows[0]['shipper']==NAMES['shipper'] and rows[0]['carrier']==NAMES['carrier']
    assert (await save(documents,'carrier',legal_name_ka_confirmed=False)).status_code==200
    frozen=await client.get('/api/deals/export?format=csv',headers=headers)
    assert frozen.status_code==200
    assert NAMES['carrier'] in frozen.content.decode('utf-8-sig')


@pytest.mark.asyncio
async def test_auth_status_and_selected_export_rows_precede_name_gate(documents):
    client=documents['client'];headers=documents['headers']['carrier']
    pending=await accepted_deal(documents,'cargo')
    assert (await client.get(f'/api/deals/{pending}/act.pdf',headers=headers)).status_code==400
    unrelated=await outsider(documents)
    assert (await client.get(f'/api/deals/{pending}/act.pdf',headers=unrelated)).status_code==403
    assert (await client.get(f'/api/deals/{pending}/act.pdf')).status_code in(401,403)
    assert (await client.get('/api/deals/999999/act.pdf',headers=headers)).status_code==404
    await complete(documents,'transport');await confirm_names(documents)
    async with documents['sessions']() as db:
        owner=(await db.execute(select(User).where(User.email=='carrier@example.test'))).scalar_one()
        third=(await db.execute(select(User).where(User.email=='outsider@example.test'))).scalar_one()
        db.add(Deal(shipper_id=third.id,carrier_id=owner.id,status=DealStatus.confirmed))
        await db.commit()
    assert (await client.get('/api/deals/export?format=csv&status=completed',headers=headers)).status_code==200
    assert (await client.get('/api/deals/export?format=csv',headers=headers)).status_code==409


@pytest.mark.asyncio
async def test_account_deletion_erases_private_name_and_confirmation(documents):
    assert (await save(documents,legal_name_ka=NAMES['shipper'],legal_name_ka_confirmed=True)).status_code==200
    response=await documents['client'].request('DELETE','/api/users/me',headers=documents['headers']['shipper'],
        json={'confirmation':'УДАЛИТЬ','current_password':'JourneyTest39!'})
    assert response.status_code==200,response.text
    async with documents['sessions']() as db:
        user=(await db.execute(select(User).where(User.is_deleted.is_(True)))).scalar_one()
        assert user.legal_name_ka is None and user.legal_name_ka_confirmed_at is None


def test_export_timestamp_accepts_naive_sqlite_and_normalizes_aware_offsets():
    assert deals._export_timestamp(None) is None
    assert deals._export_timestamp(datetime(2026,7,1,12))==datetime(2026,7,1,12,tzinfo=timezone.utc)
    assert deals._export_timestamp(datetime(2026,7,2,1,tzinfo=timezone(timedelta(hours=4))))==datetime(2026,7,1,21,tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize('format',['json','csv'])
async def test_date_filtered_exports_include_the_whole_end_day_and_exclude_outside_period(documents,format):
    await confirm_names(documents)
    stamps=[datetime(2026,6,30,23,59,59,999999,tzinfo=timezone.utc),
            datetime(2026,7,1,tzinfo=timezone.utc),datetime(2026,7,1,12,tzinfo=timezone.utc),
            datetime(2026,7,1,23,59,59,999999,tzinfo=timezone.utc),datetime(2026,7,2,tzinfo=timezone.utc)]
    async with documents['sessions']() as db:
        people={user.role.value:user.id for user in (await db.execute(select(User))).scalars().all()}
        rows=[Deal(shipper_id=people['shipper'],carrier_id=people['carrier'],status=DealStatus.completed,
                   shipper_confirmed=True,carrier_confirmed=True,completed_at=stamp,created_at=stamp) for stamp in stamps]
        rows.append(Deal(shipper_id=people['shipper'],carrier_id=people['carrier'],status=DealStatus.confirmed,
                         created_at=datetime(2026,7,1,3,tzinfo=timezone.utc)))
        db.add_all(rows);await db.commit()
        ids=[row.id for row in rows]
    cases=[({'from':'2026-07-01','to':'2026-07-01'},set(ids[1:4]+ids[5:])),
           ({'from':'2026-07-01'},set(ids[1:])),({'to':'2026-07-01'},set(ids[:4]+ids[5:])),
           ({'from':'2026-07-03','to':'2026-07-04'},set())]
    for dates,expected in cases:
        response=await documents['client'].get('/api/deals/export',params={'format':format,**dates},headers=documents['headers']['shipper'])
        assert response.status_code==200,response.text
        if format=='json':
            actual={row['deal_id'] for row in response.json()['deals']}
            assert response.json()['count']==len(expected)
        else:
            exported=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
            actual={int(row['deal_id']) for row in exported if str(row.get('deal_id','')).isdigit()}
            assert all(row['shipper']==NAMES['shipper'] and row['carrier']==NAMES['carrier'] for row in exported if str(row.get('deal_id','')).isdigit())
        assert actual==expected
