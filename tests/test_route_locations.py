"""Typed location contracts: isolated SQLite and deterministic own fixture points."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.database import Base, get_db
from app.routers.auth import require_user
from app.models.user import User, UserPlan
from app.models.load import Load
from app.models.transport_offer import TransportOffer
from app.services.route_locations import resolution_token, verified_token, RouteLocationInput
from scripts.prepare_loading_period import prepare_route_locations

CATALOG = [{'key':'ge:checkpoint:test-dariali', 'kind':'border_checkpoint',
            'label_ru':'КПП Дарьял', 'label_ge':'დარიალი', 'label_en':'Dariali checkpoint',
            'country_iso':'GE', 'lat':42.0, 'lon':44.0,
            'aliases':['Дарьял','Дариали','Dariali','დარიალი'], 'address':'Test checkpoint address'}]

@pytest_asyncio.fixture
async def context():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(User(id=9901,email='address-only@example.test',hashed_password='not-used',
                    company_name='Disposable address test',plan=UserPlan.pro_plus))
        await db.commit()
    async def db_override():
        async with sessions() as db:
            yield db
    async def user_override():
        async with sessions() as db:
            return await db.get(User,9901)
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[require_user] = user_override
    with (patch('app.services.route_locations.location_catalog', return_value=CATALOG),
          patch('app.services.route_locations.resolve_country', new=AsyncMock(return_value='GE')),
          patch('app.services.exchange_rate.get_usd_gel_rate', new=AsyncMock(return_value=2.7)),
          patch('app.services.subscription_matcher.notify_subscribers', new=AsyncMock()),
          patch('app.services.transport_matcher.notify_transport_subscribers', new=AsyncMock())):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client, sessions
    app.dependency_overrides.pop(require_user, None)
    await engine.dispose()

async def point(client, **changes):
    response = await client.post('/api/locations/resolve', json={
        'lat':41.70123456789,'lon':44.81234567891,'label':'Warehouse access gate',
        'address':'User-described loading point', **changes})
    assert response.status_code == 200, response.text
    return response.json()['location']

def load_data(location):
    return {'from_city':'Untrusted street text', 'to_city':'Batumi',
            'from_location':location,'weight_kg':1500,'truck_type':'tent','price_gel':200,
            'load_date':(datetime.now(timezone.utc)+timedelta(days=2)).date().isoformat()}

def offer_data(location):
    return {'from_city':'Untrusted street text','to_city':'Батуми','from_location':location,
            'capacity_kg':1500,'truck_type':'tent',
            'available_from':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()}

@pytest.mark.asyncio
async def test_suggestions_are_fast_own_catalog_and_support_all_checkpoint_aliases(context):
    client,_=context
    for name in ('Дарьял','Дариали','Dariali','დარიალი'):
        response=await client.get('/api/locations/suggest',params={'q':name})
        assert response.status_code==200,response.text
        assert [row['key'] for row in response.json()['results']]==[CATALOG[0]['key']]
        assert response.json()['source']=='own_catalog'
    response=await client.get('/api/locations/suggest',params={'q':'','limit':250})
    assert any(row['kind']=='settlement' for row in response.json()['results'])
    assert any(row['kind']=='border_checkpoint' for row in response.json()['results'])

@pytest.mark.asyncio
async def test_map_resolve_requires_server_verified_country(context):
    client,_=context
    response=await client.post('/api/locations/resolve',json={'lat':41.7,'lon':44.8,'country_iso':'RU'})
    assert response.status_code==422
    with patch('app.services.route_locations.resolve_country',new=AsyncMock(return_value=None)):
        response=await client.post('/api/locations/resolve',json={'lat':41.7,'lon':44.8})
    assert response.status_code==422
    resolved=await point(client)
    assert resolved['country_iso']=='GE' and resolved['settlement_id'] is None
    assert resolved['resolution_token']

@pytest.mark.parametrize('field,value',[('lat',True),('lat',91),('lon',181),('lon','nan')])
@pytest.mark.asyncio
async def test_invalid_map_coordinates_are_rejected(context,field,value):
    client,_=context
    response=await client.post('/api/locations/resolve',json={'lat':41.7,'lon':44.8,field:value})
    assert response.status_code==422

@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_exact_point_survives_create_refresh_edit_and_owned_listing(context,source):
    client,sessions=context
    location=await point(client)
    body=load_data(location) if source=='loads' else offer_data(location)
    response=await client.post('/api/'+source+'/',json=body)
    assert response.status_code in(200,201),response.text
    row=response.json() if source=='loads' else response.json()['offer']
    saved=row['from_location']
    assert saved['lat']==location['lat'] and saved['lon']==location['lon']
    assert saved['country_iso']=='GE' and saved['label']=='Warehouse access gate'
    assert saved['settlement_id'] is None and 'resolution_token' not in saved
    assert row['route_scope']=='local'
    model=Load if source=='loads' else TransportOffer
    async with sessions() as db:
        stored=await db.get(model,row['id'])
        assert stored.from_city=='Warehouse access gate' and stored.from_city_id is None
        assert stored.from_location==saved
    patch_url='/api/'+source+'/'+str(row['id'])
    edited={**saved,'label':'Correct loading gate'}
    update=await (client.put(patch_url,json={'from_location':edited}) if source=='loads'
                  else client.patch(patch_url,json={'from_location':edited}))
    assert update.status_code==200,update.text
    edited_row=update.json() if source=='loads' else update.json()['offer']
    assert edited_row['from_location']['label']=='Correct loading gate'
    mine=await client.get('/api/loads/my/loads' if source=='loads' else '/api/transport/my')
    collection='loads' if source=='loads' else 'offers'
    assert mine.json()[collection][0]['from_location']['lat']==location['lat']
    public=await client.get('/api/'+source+'/',params={'scope':'local'})
    assert any(x['id']==row['id'] for x in public.json()[collection])
    public=await client.get('/api/'+source+'/',params={'scope':'intl'})
    assert not public.json()[collection]
    changed_city=await(client.put(patch_url,json={'from_city':'Тбилиси'}) if source=='loads'
                       else client.patch(patch_url,json={'from_city':'Тбилиси'}))
    assert changed_city.status_code==200,changed_city.text
    final=changed_city.json() if source=='loads' else changed_city.json()['offer']
    assert final['from_location'] is None

@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_signed_country_enforces_international_scope(context,source):
    client,_=context
    with patch('app.services.route_locations.resolve_country',new=AsyncMock(return_value='RU')):
        location=await point(client,lat=43.01,lon=44.68)
    body=load_data(location) if source=='loads' else offer_data(location)
    response=await client.post('/api/'+source+'/',json=body)
    assert response.status_code in(200,201),response.text
    row=response.json() if source=='loads' else response.json()['offer']
    assert row['route_scope']=='intl'
    collection='loads' if source=='loads' else 'offers'
    local=await client.get('/api/'+source+'/',params={'scope':'local'})
    intl=await client.get('/api/'+source+'/',params={'scope':'intl'})
    assert not local.json()[collection] and len(intl.json()[collection])==1

@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_checkpoint_is_not_faked_as_city_and_alias_filter_matches(context,source):
    client,_=context
    suggestions=await client.get('/api/locations/suggest',params={'q':'Дарьял'})
    location=suggestions.json()['results'][0]
    body=load_data(location) if source=='loads' else offer_data(location)
    response=await client.post('/api/'+source+'/',json=body)
    assert response.status_code in(200,201),response.text
    row=response.json() if source=='loads' else response.json()['offer']
    assert row['from_city_id'] is None and row['route_scope']=='local'
    assert row['from_location']['key']==CATALOG[0]['key']
    collection='loads' if source=='loads' else 'offers'
    for query in ({'from_city':'Дарьял'},{'from_city':'Dariali'},
                  {'from_city':'დარიალი'},{'from_location_key':CATALOG[0]['key']}):
        found=await client.get('/api/'+source+'/',params={'scope':'local',**query})
        assert found.status_code==200,found.text
        assert len(found.json()[collection])==1

@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'lat':41.8},{'country_iso':'RU'},{'resolution_token':'forged'}])
async def test_forged_map_point_cannot_be_published(context,change):
    client,sessions=context
    location={**await point(client),'label_mode':'custom',**change}
    response=await client.post('/api/loads/',json=load_data(location))
    assert response.status_code==422,response.text
    async with sessions() as db:
        assert not (await db.execute(select(Load))).scalars().all()

@pytest.mark.asyncio
async def test_moving_checkpoint_cannot_relabel_road_or_wrong_country_as_checkpoint(context):
    client,_=context
    location=(await client.get('/api/locations/suggest',params={'q':'Dar'})).json()['results'][0]
    location['lat']+=0.1
    response=await client.post('/api/transport/',json=offer_data(location))
    assert response.status_code==422


def test_signed_token_expiry_and_coordinates_are_exact():
    token=resolution_token(41.7,44.8,'GE',now=100)
    assert verified_token(token,41.7,44.8,now=101)=='GE'
    for args in [(41.700000001,44.8,None,101),(41.7,44.8,'RU',101),(41.7,44.8,None,86501)]:
        with pytest.raises(ValueError):
            verified_token(token,args[0],args[1],args[2],args[3])

@pytest.mark.asyncio
async def test_route_location_schema_is_additive_nullable_repeatable_and_has_no_backfill():
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as connection:
            for table in ('loads','transport_offers'):
                await connection.execute(text('CREATE TABLE '+table+' (id INTEGER PRIMARY KEY)'))
                await connection.execute(text('INSERT INTO '+table+' VALUES (1)'))
            await connection.run_sync(prepare_route_locations)
            await connection.run_sync(prepare_route_locations)
            for table in ('loads','transport_offers'):
                row=(await connection.execute(text('SELECT id,from_location,to_location FROM '+table))).first()
                assert row==(1,None,None)
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_route_location_schema_refuses_incompatible_existing_column():
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE TABLE loads (id INTEGER PRIMARY KEY,from_location TEXT NOT NULL)'))
            with pytest.raises(RuntimeError,match='from_location'):
                await connection.run_sync(prepare_route_locations)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_explicit_provider_locality_preserves_city_search_while_exact_address_pin_persists(context,source):
    client,_=context
    location=await point(client,label='Тбилиси, Warehouse gate 7',settlement_key='ge:tbilisi')
    assert location['settlement_key']=='ge:tbilisi'
    body=load_data(location) if source=='loads' else offer_data(location)
    body['from_city']='Тбилиси'
    response=await client.post('/api/'+source+'/',json=body)
    assert response.status_code in(200,201),response.text
    row=response.json() if source=='loads' else response.json()['offer']
    assert (row['from'] if source=='loads' else row['from_city'])=='Тбилиси'
    assert row['from_city_key']=='ge:tbilisi'
    assert row['from_location']['lat']==location['lat']
    collection='loads' if source=='loads' else 'offers'
    for name in ('Тбилиси','Tbilisi','თბილისი'):
        found=await client.get('/api/'+source+'/',params={'from_city':name,'scope':'local'})
        assert len(found.json()[collection])==1

@pytest.mark.asyncio
async def test_map_pin_does_not_accept_settlement_from_another_country(context):
    client,_=context
    response=await client.post('/api/locations/resolve',json={
        'lat':41.7,'lon':44.8,'settlement_key':'ru:moscow'})
    assert response.status_code==422

@pytest.mark.asyncio
async def test_canonical_settlement_selection_saves_canonical_city_id(context):
    client,_=context
    suggestions=await client.get('/api/locations/suggest',params={'q':'Tbilisi'})
    location=next(row for row in suggestions.json()['results'] if row['key']=='ge:tbilisi')
    response=await client.post('/api/loads/',json=load_data(location))
    assert response.status_code==200,response.text
    row=response.json()
    assert row['from']=='Тбилиси' and row['from_city_id']
    assert row['from_location']['key']=='ge:tbilisi'
    assert row['from_location']['lat']==location['lat']


@pytest.mark.asyncio
async def test_map_pin_without_postal_address_still_resolves_and_saves(context):
    client,_=context
    location=await point(client,address='')
    assert location['address']=='Warehouse access gate'
    created=await client.post('/api/loads/',json=load_data(location))
    assert created.status_code==200,created.text

@pytest.mark.asyncio
async def test_checkpoint_label_can_be_renamed_without_losing_trusted_key_or_country(context):
    client,_=context
    location=(await client.get('/api/locations/suggest',params={'q':'Дарьял'})).json()['results'][0]
    location['label']='Gate for cargo pickup'
    created=await client.post('/api/loads/',json=load_data(location))
    assert created.status_code==200,created.text
    saved=created.json()['from_location']
    assert saved['label']==location['label']
    assert saved['key']==CATALOG[0]['key'] and saved['lat']==CATALOG[0]['lat']
    assert 'Дарьял' in saved['aliases']


def test_checkpoint_languages_match_while_opposite_sides_remain_distinct(context=None):
    from app.services.city_identity import same_city
    assert same_city('Дарьял','Dariali')
    assert same_city('Дарьял','დარიალი')
    assert not same_city('Дарьял','Верхний Ларс')
    assert not same_city('Дарьял','Степанцминда')

@pytest.mark.asyncio
async def test_renamed_checkpoint_subscriptions_match_saved_country_specific_key(context):
    from app.services.city_identity import endpoint_match_value, same_city
    from app.models.subscription import RouteSubscription
    from app.services.subscription_matcher import find_matching_subscriptions
    client,sessions=context
    row=CATALOG[0]
    async with sessions() as db:
        db.add(User(id=9902,email='address-subscriber@example.test',hashed_password='unused'))
        db.add_all([
            RouteSubscription(user_id=9902,from_city='Tbilisi',to_city='Dariali',is_active=True),
            RouteSubscription(user_id=9902,from_city='Tbilisi',to_city='Верхний Ларс',is_active=True)])
        await db.flush()
        load=Load(user_id=9901,from_city='Тбилиси',to_city='Custom cargo gate name',
                  weight_kg=1000,truck_type='tent',load_date=datetime.now(timezone.utc)+timedelta(days=1),
                  to_location={'kind':'border_checkpoint','key':row['key'],
                               'label':'Custom cargo gate name','country_iso':'GE',
                               'lat':row['lat'],'lon':row['lon']})
        matches=await find_matching_subscriptions(load,db)
        assert len(matches)==1 and matches[0].to_city=='Dariali'
        assert endpoint_match_value(load,'to')==row['key']

@pytest.mark.asyncio
async def test_checkpoint_key_and_query_disagreement_is_rejected(context):
    client,_=context
    response=await client.get('/api/loads/',params={
        'from_location_key':CATALOG[0]['key'],'from_city':'Москва'})
    assert response.status_code==422


@pytest.mark.asyncio
async def test_settlement_id_and_key_must_identify_same_city(context):
    client,_=context
    location=next(row for row in (await client.get('/api/locations/suggest',params={'q':'Batumi'})).json()['results']
                  if row['key']=='ge:batumi')
    # Persist Batumi first so it has a canonical DB ID, then deliberately mix IDs.
    first=await client.post('/api/loads/',json=load_data(location))
    assert first.status_code==200,first.text
    saved=first.json()['from_location']
    saved['key']='ge:tbilisi'
    second=await client.post('/api/loads/',json=load_data(saved))
    assert second.status_code==422


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_unknown_location_key_cannot_be_masked_by_matching_text(context,source):
    client,_=context
    response=await client.get('/api/'+source+'/',params={
        'from_location_key':'ge:invented-checkpoint','from_city':'Дарьял'})
    assert response.status_code==422


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
@pytest.mark.parametrize('kind',['point','settlement','border_checkpoint'])
async def test_label_provenance_survives_create_update_and_public_owned_serialization(context,source,kind):
    client,sessions=context
    if kind=='point':
        location=await point(client,label='Dariali monastery',label_mode='auto')
        assert location['label_mode']=='auto'
    else:
        rows=(await client.get('/api/locations/suggest',params={'q':'Tbilisi' if kind=='settlement' else 'Dar'})).json()['results']
        location={**next(row for row in rows if row['kind']==kind),'label_mode':'auto'}
    body=load_data(location) if source=='loads' else offer_data(location)
    created=await client.post('/api/'+source+'/',json=body)
    assert created.status_code in(200,201),created.text
    saved=created.json() if source=='loads' else created.json()['offer']
    auto=saved['from_location']
    assert auto['label_mode']=='auto'
    assert auto['lat']==location['lat'] and auto['lon']==location['lon']
    update_url='/api/'+source+'/'+str(saved['id'])
    custom={**auto,'label':'My loading gate','label_mode':'custom'}
    updated=await(client.put(update_url,json={'from_location':custom}) if source=='loads'
                  else client.patch(update_url,json={'from_location':custom}))
    assert updated.status_code==200,updated.text
    updated_row=updated.json() if source=='loads' else updated.json()['offer']
    expected=updated_row['from_location']
    assert expected['label_mode']=='custom' and expected['label']=='My loading gate'
    for key in ('lat','lon','key','country_iso','settlement_id','settlement_key'):
        assert expected.get(key)==auto.get(key)
    assert 'resolution_token' not in expected
    unrelated=await(client.put(update_url,json={'description':'Updated loading instructions'}) if source=='loads'
                    else client.patch(update_url,json={'description':'Updated loading instructions'}))
    assert unrelated.status_code==200,unrelated.text
    collection='loads' if source=='loads' else 'offers'
    mine=await client.get('/api/loads/my/loads' if source=='loads' else '/api/transport/my')
    public=await client.get('/api/'+source+'/',params={'scope':'local'})
    assert mine.json()[collection][0]['from_location']==expected
    assert public.json()[collection][0]['from_location']==expected
    model=Load if source=='loads' else TransportOffer
    async with sessions() as db:
        assert (await db.get(model,saved['id'])).from_location==expected


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_old_location_callers_do_not_get_invented_label_provenance(context,source):
    client,_=context
    location=await point(client)
    assert 'label_mode' not in location
    body=load_data(location) if source=='loads' else offer_data(location)
    created=await client.post('/api/'+source+'/',json=body)
    assert created.status_code in(200,201),created.text
    row=created.json() if source=='loads' else created.json()['offer']
    assert 'label_mode' not in row['from_location']
    url='/api/'+source+'/'+str(row['id'])
    updated=await(client.put(url,json={'description':'Old client unchanged point'}) if source=='loads'
                  else client.patch(url,json={'description':'Old client unchanged point'}))
    assert updated.status_code==200,updated.text
    final=updated.json() if source=='loads' else updated.json()['offer']
    assert final['from_location']==row['from_location']


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_moving_saved_automatic_poi_uses_fresh_signed_point_and_new_label(context,source):
    client,_=context
    old=await point(client,lat=42.735488913518935,lon=44.63132098317131,
                    label='Dariali monastery',address='Kazbegi municipality',label_mode='auto')
    created=await client.post('/api/'+source+'/',json=load_data(old) if source=='loads' else offer_data(old))
    assert created.status_code in(200,201),created.text
    row=created.json() if source=='loads' else created.json()['offer']
    moved=await point(client,lat=41.904737,lon=44.600335,label='Dzveli Kanda, street 1',label_mode='auto')
    url='/api/'+source+'/'+str(row['id'])
    updated=await(client.put(url,json={'from_location':moved}) if source=='loads'
                  else client.patch(url,json={'from_location':moved}))
    assert updated.status_code==200,updated.text
    final=updated.json() if source=='loads' else updated.json()['offer']
    assert final['from_location']['label']=='Dzveli Kanda, street 1'
    assert final['from_location']['label_mode']=='auto'
    assert final['from_location']['lat']==41.904737 and final['from_location']['lon']==44.600335


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['manual',True,{}])
async def test_invalid_label_provenance_is_rejected(context,mode):
    client,_=context
    resolved=await client.post('/api/locations/resolve',json={'lat':41.7,'lon':44.8,'label_mode':mode})
    assert resolved.status_code==422,resolved.text


PRESENTATION = {
    'localized': {'ru': {'label':'Продукты','address':'Дзвели Канда, Грузия'},
                  'ka': {'label':'სურსათი','address':'ძველი ქანდა, საქართველო'}},
    'context': {'relation':'nearby','names':{'ru':'Дзвели Канда','ka':'ძველი ქანდა'},
                'source':'fixture','country_iso':'GE'},
}


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint',['resolve','presentation'])
@pytest.mark.parametrize('requested',[False,True])
async def test_presentation_endpoint_is_read_only_and_keeps_raw_label_and_coordinates(context,endpoint,requested):
    client,sessions=context
    with (patch.dict('os.environ',{'LOCATION_PRESENTATION_ENABLED':'false'}),
          patch('app.services.location_presentation._reverse_snapshots',new=AsyncMock(side_effect=AssertionError('No provider calls allowed'))) as provider):
        response=await client.post('/api/locations/'+endpoint,json={
            'lat':41.904737,'lon':44.600335,'label':'My warehouse gate','label_mode':'custom',
            'include_presentation':requested,**PRESENTATION})
    assert response.status_code==200,response.text
    location=response.json()['location']
    assert location['label']=='My warehouse gate' and location['label_mode']=='custom'
    assert location['lat']==41.904737 and location['lon']==44.600335
    assert location['localized']==PRESENTATION['localized'] and location['context']==PRESENTATION['context']
    assert location['settlement_id'] is None and location['settlement_key'] is None
    assert verified_token(location['resolution_token'],41.904737,44.600335)=='GE'
    provider.assert_not_called()
    async with sessions() as db:
        assert not (await db.execute(select(Load))).scalars().all()
        assert not (await db.execute(select(TransportOffer))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize('source',['loads','transport'])
async def test_bilingual_context_persists_and_same_point_omissions_merge_but_move_drops_old(context,source):
    client,_=context
    location=await point(client,label='Продукты',label_mode='auto',**PRESENTATION)
    response=await client.post('/api/'+source+'/',json=load_data(location) if source=='loads' else offer_data(location))
    assert response.status_code in(200,201),response.text
    row=response.json() if source=='loads' else response.json()['offer']
    saved=row['from_location']
    assert saved['localized']==PRESENTATION['localized'] and saved['context']==PRESENTATION['context']
    url='/api/'+source+'/'+str(row['id'])
    omitted={key:value for key,value in saved.items() if key not in ('localized','context')}
    omitted.update(label='My loading gate',label_mode='custom')
    update=await(client.put(url,json={'from_location':omitted}) if source=='loads'
                 else client.patch(url,json={'from_location':omitted}))
    assert update.status_code==200,update.text
    changed=update.json() if source=='loads' else update.json()['offer']
    assert changed['from_location']['localized']==saved['localized']
    assert changed['from_location']['context']==saved['context']
    assert changed['from_location']['label']=='My loading gate'
    collection='loads' if source=='loads' else 'offers'
    public=await client.get('/api/'+source+'/',params={'scope':'local'})
    mine=await client.get('/api/loads/my/loads' if source=='loads' else '/api/transport/my')
    assert public.json()[collection][0]['from_location']==changed['from_location']
    assert mine.json()[collection][0]['from_location']==changed['from_location']
    # Even a caller copying an old display snapshot onto newly signed coords
    # cannot retain those unchanged old presentation fields after moving.
    moved={**await point(client,lat=41.91,label='New street',label_mode='auto'),**PRESENTATION}
    update=await(client.put(url,json={'from_location':moved}) if source=='loads'
                 else client.patch(url,json={'from_location':moved}))
    assert update.status_code==200,update.text
    changed=update.json() if source=='loads' else update.json()['offer']
    assert changed['from_location']['lat']==41.91
    assert 'localized' not in changed['from_location'] and 'context' not in changed['from_location']


@pytest.mark.asyncio
async def test_context_is_display_only_and_cannot_create_fake_country_or_settlement(context):
    client,_=context
    location=await point(client,context={'relation':'within','country_iso':'RU','key':'ru:moscow',
                                       'settlement_key':'ru:moscow','names':{'ru':'Москва'}})
    assert location['country_iso']=='GE' and location['settlement_key'] is None
    assert 'context' not in location
    response=await client.post('/api/loads/',json=load_data(location))
    assert response.status_code==200,response.text
    assert response.json()['route_scope']=='local' and response.json()['from_city_id'] is None
