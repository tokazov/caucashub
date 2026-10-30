"""Actual public/consent APIs on isolated SQLite and unique CI PostgreSQL schemas."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.deal import Deal, DealStatus
from app.models.deal_review import DealReview
from app.models.user import User
from app.routers import deals, users
from tests.test_publication_journeys import journey  # noqa: F401
from tests.test_deal_completion_http import complete, personal, outsider


pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def profile(journey,monkeypatch):
    journey['client']._transport.app.include_router(users.router,prefix='/api/users')
    monkeypatch.setattr(deals,'_send_completed_emails',Mock(return_value=None))
    async with journey['sessions']() as db:
        people=(await db.execute(select(User))).scalars().all()
        for user in people:
            user.legal_name_ka='შპს პირადი დოკუმენტები'
            user.legal_name_ka_confirmed_at=datetime.now(timezone.utc)
        await db.commit()
        journey['ids']={user.role.value:user.id for user in people}
    return journey


async def get_profile(context,role='carrier',**params):
    response=await context['client'].get('/api/users/'+str(context['ids'][role])+'/profile',params=params)
    assert response.status_code==200,response.text
    return response.json()


async def rate(context,deal_id,role='shipper',**body):
    return await context['client'].post(f'/api/deals/{deal_id}/rate',headers=context['headers'][role],
                                       json={'score':4,'comment':'Private text',**body})


def assert_no_private_fields(value):
    forbidden={'email','phone','inn','telegram_id','password','hashed_password','deal_id',
               'shipper_id','carrier_id','load_id','load_from','load_to','agreed_price','price',
               'act_number','notes','truck_type','tonnage','org_type','documents',
               'legal_name_ka','legal_name_ka_confirmed','legal_name_ka_confirmed_at'}
    if isinstance(value,dict):
        assert not set(value).intersection(forbidden)
        for item in value.values():
            assert_no_private_fields(item)
    elif isinstance(value,list):
        for item in value:
            assert_no_private_fields(item)


async def test_empty_profile_ignores_legacy_counters_and_only_server_verified_badge(profile):
    client=profile['client']
    async with profile['sessions']() as db:
        user=await db.get(User,profile['ids']['carrier'])
        user.rating=50;user.ratings_received_count=99;user.completed_deals_count=88;user.trips_count=77
        user.city='Тбилиси, частная улица, дом 7';user.is_verified=False
        await db.commit()
    attempted=await client.put('/api/users/me',headers=profile['headers']['carrier'],json={'is_verified':True})
    assert attempted.status_code==200,attempted.text
    result=await get_profile(profile)
    summary=result['profile']
    assert summary['rating'] is None and summary['review_count']==0 and summary['completed_deals_count']==0
    assert summary['is_new_carrier'] is True and summary['rating_verified'] is False
    assert summary['is_verified'] is False and summary['city'] is None
    assert result['reviews']==[] and result['total']==0 and result['has_more'] is False
    assert_no_private_fields(result)
    async with profile['sessions']() as db:
        user=await db.get(User,profile['ids']['carrier']);user.is_verified=True;user.city='Tbilisi';await db.commit()
    result=await get_profile(profile)
    assert result['profile']['is_verified'] is True and result['profile']['city']=='Тбилиси'
    old=await client.get('/api/users/'+str(profile['ids']['carrier']))
    assert old.json()['completed_deals_count']==0 and old.json()['trips_count']==0
    assert_no_private_fields(old.json())


@pytest.mark.parametrize('source',['cargo','transport'])
async def test_default_comments_stay_private_but_real_score_count_and_dates_are_public(profile,source):
    deal_id,_=await complete(profile,source)
    rating=await rate(profile,deal_id,comment='Never retroactively public')
    assert rating.status_code==200,rating.text
    assert rating.json()['my_review']['public_comment'] is False
    data=await get_profile(profile)
    assert data['profile']['rating']==4 and data['profile']['review_count']==1
    assert data['profile']['completed_deals_count']==1 and data['total']==1
    review=data['reviews'][0]
    assert review['score']==4 and review['created_at'] and review['comment'] is None
    assert review['public_comment'] is False and review['author']['id']==profile['ids']['shipper']
    own=await personal(profile,'shipper',deal_id)
    peer=await personal(profile,'carrier',deal_id)
    assert own['my_review']['comment']=='Never retroactively public'
    assert peer['counterparty_review']['comment']=='Never retroactively public'
    assert_no_private_fields(data)


async def test_only_author_can_change_visibility_and_never_mutate_score_or_private_comment(profile):
    deal_id,_=await complete(profile,'cargo')
    original='Доставлено: private@example.test, +995 (599) 000001, ИНН404123456'
    assert (await rate(profile,deal_id,comment=original)).status_code==200
    client=profile['client'];url=f'/api/deals/{deal_id}/review-visibility'
    assert (await client.patch(url,json={'public_comment':True})).status_code in(401,403)
    unrelated=await outsider(profile)
    assert (await client.patch(url,headers=unrelated,json={'public_comment':True})).status_code==403
    assert (await client.patch(url,headers=profile['headers']['carrier'],json={'public_comment':True})).status_code==404
    for body in ({'public_comment':'true'},{'public_comment':1},{'public_comment':None},{},
                 {'public_comment':True,'score':1},{'public_comment':True,'comment':'Changed'}):
        response=await client.patch(url,headers=profile['headers']['shipper'],json=body)
        assert response.status_code==422,response.text
    before=(await get_profile(profile))['reviews'][0]
    for visible in (True,True,False):
        response=await client.patch(url,headers=profile['headers']['shipper'],json={'public_comment':visible})
        assert response.status_code==200,response.text
        assert response.json()['my_review']['comment']==original and response.json()['my_review']['score']==4
        result=await get_profile(profile);review=result['reviews'][0]
        assert review['id']==before['id'] and review['created_at']==before['created_at']
        assert result['profile']['rating']==4 and result['total']==1
        if visible:
            assert review['public_comment'] is True and '•••' in review['comment']
            assert all(contact not in review['comment'] for contact in ('private@example.test','599','404123456'))
        else:
            assert review['public_comment'] is False and review['comment'] is None
    assert (await personal(profile,'shipper',deal_id))['my_review']['comment']==original
    responses=await client.get('/api/responses/my',headers=profile['headers']['carrier'])
    assert responses.json()['responses'][0]['shipper_id']==profile['ids']['shipper']


@pytest.mark.parametrize('value',['true',1,None])
async def test_new_rating_public_comment_boolean_is_strict(profile,value):
    deal_id,_=await complete(profile,'cargo')
    response=await rate(profile,deal_id,public_comment=value)
    assert response.status_code==422,response.text
    assert (await get_profile(profile))['reviews']==[]


async def test_explicit_new_public_comment_is_visible_and_name_contacts_are_masked(profile):
    deal_id,_=await complete(profile,'cargo')
    async with profile['sessions']() as db:
        author=await db.get(User,profile['ids']['shipper']);author.company_name='Trader author@example.test +995599000001';await db.commit()
    response=await rate(profile,deal_id,public_comment=True,comment='Хорошая доставка')
    assert response.status_code==200,response.text
    result=await get_profile(profile);review=result['reviews'][0]
    assert review['public_comment'] is True and review['comment']=='Хорошая доставка'
    assert review['author']['name']=='Trader ••• •••'
    async with profile['sessions']() as db:
        user=await db.get(User,profile['ids']['carrier']);user.company_name=None;user.full_name=None;await db.commit()
    anonymous=await get_profile(profile)
    assert anonymous['profile']['name']=='Участник CaucasHub'
    assert 'carrier@example.test' not in str(anonymous)


async def test_both_roles_receive_their_own_independent_review_and_completed_count(profile):
    deal_id,_=await complete(profile,'transport')
    assert (await rate(profile,deal_id,'shipper',score=4,comment='Private shipper text')).status_code==200
    assert (await rate(profile,deal_id,'carrier',score=5,comment='Public carrier text',public_comment=True)).status_code==200
    carrier=await get_profile(profile,'carrier')
    shipper=await get_profile(profile,'shipper')
    assert carrier['profile']['rating']==4 and carrier['reviews'][0]['comment'] is None
    assert shipper['profile']['rating']==5 and shipper['reviews'][0]['comment']=='Public carrier text'
    assert shipper['reviews'][0]['author']['role']=='carrier'
    assert all(result['profile']['review_count']==result['profile']['completed_deals_count']==1 for result in (carrier,shipper))


async def test_pagination_ties_and_counts_share_the_same_confirmed_review_predicate(profile):
    shipper,carrier=profile['ids']['shipper'],profile['ids']['carrier']
    when=datetime(2026,1,1,tzinfo=timezone.utc)
    await outsider(profile)
    async with profile['sessions']() as db:
        third=(await db.execute(select(User).where(User.email=='outsider@example.test'))).scalar_one()
        for number in range(13):
            deal=Deal(shipper_id=shipper,carrier_id=carrier,status=DealStatus.completed,
                      shipper_confirmed=True,carrier_confirmed=True,agreed_price=999,notes='Never public')
            db.add(deal);await db.flush()
            db.add(DealReview(deal_id=deal.id,rater_id=shipper,recipient_id=carrier,score=3,
                              comment='Old private text',created_at=when))
        # Historical malformed authorship must not count in either list or average.
        db.add(DealReview(deal_id=deal.id,rater_id=third.id,recipient_id=carrier,score=1,
                          public_comment=True,comment='Not a counterparty',created_at=when))
        # A truly completed deal without a review contributes to deal count only.
        db.add(Deal(shipper_id=shipper,carrier_id=carrier,status=DealStatus.completed,
                    shipper_confirmed=True,carrier_confirmed=True,agreed_price=50))
        for status,confirmed in ((DealStatus.completed,False),(DealStatus.confirmed,True),(DealStatus.canceled,True)):
            deal=Deal(shipper_id=shipper,carrier_id=carrier,status=status,
                      shipper_confirmed=confirmed,carrier_confirmed=True,agreed_price=50)
            db.add(deal);await db.flush()
            db.add(DealReview(deal_id=deal.id,rater_id=shipper,recipient_id=carrier,score=1,public_comment=True,comment='Ineligible'))
        await db.commit()
    first=await get_profile(profile,limit=10,offset=0)
    second=await get_profile(profile,limit=10,offset=10)
    assert first['total']==second['total']==13 and first['profile']['review_count']==13
    assert first['profile']['rating']==3 and first['profile']['completed_deals_count']==14
    assert first['has_more'] is True and second['has_more'] is False
    identifiers=[row['id'] for row in first['reviews']+second['reviews']]
    assert len(identifiers)==len(set(identifiers))==13 and identifiers==sorted(identifiers,reverse=True)
    assert all(row['comment'] is None for row in first['reviews']+second['reviews'])
    assert (await get_profile(profile,offset=100))['reviews']==[]
    for params in ({'limit':0},{'limit':51},{'offset':-1}):
        response=await profile['client'].get(f'/api/users/{carrier}/profile',params=params)
        assert response.status_code==422,response.text


@pytest.mark.parametrize('state',['deleted','blocked'])
async def test_unavailable_recipient_404_and_author_fallback_keeps_only_score_and_date(profile,state):
    deal_id,_=await complete(profile,'cargo')
    assert (await rate(profile,deal_id,public_comment=True)).status_code==200
    async with profile['sessions']() as db:
        author=await db.get(User,profile['ids']['shipper'])
        if state=='deleted':author.is_deleted=True
        else:author.is_active=False
        await db.commit()
    result=await get_profile(profile);review=result['reviews'][0]
    assert result['profile']['review_count']==1 and review['score']==4 and review['created_at']
    assert review['author']=={'id':None,'name':'Участник CaucasHub','role':None,'available':False}
    assert review['comment'] is None and review['public_comment'] is False
    client=profile['client'];user_id=profile['ids']['shipper']
    for path in (f'/api/users/{user_id}/profile',f'/api/users/{user_id}', '/api/users/999999/profile'):
        assert (await client.get(path)).status_code==404
