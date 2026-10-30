"""Presentation-only metadata and mocked provider. Never contacts paid services."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.services import location_presentation as presentation
from app.services.route_locations import RouteLocationInput


META = {'localized': {'ru': {'label': 'Продукты', 'address': 'Грузия, Дзвели Канда'},
                      'ka': {'label': 'სურსათი', 'address': 'საქართველო, ძველი ქანდა'}},
        'context': {'relation': 'nearby', 'names': {'ru': 'Дзвели Канда', 'ka': 'ძველი ქანდა'},
                    'country_iso': 'GE', 'source': 'fixture'}}


def location(**extra):
    return RouteLocationInput.model_validate({'kind':'point','label':'Продукты','label_mode':'auto',
                                              'lat':41.904737,'lon':44.600335,**extra})


def snapshots():
    return [
        {'osm_id':12,'osm_type':'node','lat':'41.9047','lon':'44.6003','distance':4,
         'display_name':'Продукты, Дзвели Канда, Мцхета-Мтианети, Грузия',
         'namedetails':{'name':'სურსათი','name:ru':'Продукты','name:ka':'სურსათი'},
         'address':{'village':'Дзвели Канда','state':'Мцхета-Мтианети','country_code':'ge'}},
        {'osm_id':12,'osm_type':'node','lat':'41.9047','lon':'44.6003','distance':4,
         'display_name':'სურსათი, ძველი ქანდა, მცხეთა-მთიანეთი, საქართველო',
         'namedetails':{'name':'სურსათი','name:ru':'Продукты','name:ka':'სურსათი'},
         'address':{'village':'ძველი ქანდა','state':'მცხეთა-მთიანეთი','country_code':'ge'}},
    ]


@pytest.fixture(autouse=True)
def no_provider_and_clean_cache(monkeypatch):
    monkeypatch.delenv('LOCATION_PRESENTATION_ENABLED',raising=False)
    monkeypatch.setattr('app.services.geocoder.LOCATIONIQ_KEY','')
    monkeypatch.delenv('LOCATIONIQ_KEY',raising=False)
    presentation._cache.clear()
    presentation._inflight.clear()
    presentation._lookup_times.clear()


def test_bounded_nested_schema_sanitizes_and_ignores_unknown_routing_fields():
    value=location(**META)
    raw=value.model_dump(exclude_none=True)
    assert raw['localized']==META['localized'] and raw['context']==META['context']
    clean=location(localized={'ka':{'label':'  მაღაზია  ','address':'  საქართველო  ','lat':0},'en':{'label':'ignored'}},
                   context={**META['context'],'settlement_key':'ru:moscow','lat':0})
    assert clean.localized.model_dump(exclude_none=True)=={'ka':{'label':'მაღაზია','address':'საქართველო'}}
    assert 'settlement_key' not in clean.context.model_dump() and 'lat' not in clean.context.model_dump()


@pytest.mark.parametrize('extra',[
    {'localized':{'ka':{'label':'x'*201}}},
    {'localized':{'ru':{'address':'x'*501}}},
    {'context':{'relation':'within','names':{'ru':'x'*201}}},
    {'context':{'relation':'confirmed','names':{'ru':'test'}}},
    {'context':{'relation':'nearby','names':{'ru':'test'},'distance_m':True}},
    {'context':{'relation':'nearby','names':{'ru':'test'},'distance_m':float('nan')}},
])
def test_invalid_presentation_is_rejected(extra):
    with pytest.raises(ValidationError):
        location(**extra)


def test_same_point_omissions_preserve_both_languages_and_context():
    old={**location().model_dump(exclude_none=True),'country_iso':'GE',**deepcopy(META)}
    fields=presentation.presentation_fields(location(localized={'ru':{'address':'Новый адрес'}}),old,country='GE')
    assert fields['localized']['ru']=={'label':'Продукты','address':'Новый адрес'}
    assert fields['localized']['ka']==META['localized']['ka']
    assert fields['context']==META['context']
    assert old['localized']==META['localized']


def test_moving_drops_omitted_or_copied_old_snapshots_without_snapping():
    old={**location().model_dump(exclude_none=True),'country_iso':'GE',**deepcopy(META)}
    assert presentation.presentation_fields(location(lat=41.91),old,country='GE')=={}
    assert presentation.presentation_fields(location(lat=41.91,**META),old,country='GE')=={}
    fresh={'localized':{'ka':{'address':'თბილისი'}},'context':{'relation':'nearby','names':{'ka':'თბილისი'}}}
    assert presentation.presentation_fields(location(lat=41.91,**fresh),old,country='GE')==fresh


def test_foreign_context_never_changes_country_and_is_discarded():
    fields=presentation.presentation_fields(location(context={**META['context'],'country_iso':'RU','key':'ru:moscow'}),country='GE')
    assert fields=={}


def test_empty_presentation_has_no_fake_backfill():
    assert presentation.presentation_fields(location(),country='GE')=={}
    assert presentation.presentation_fields(location(localized={'ka':{}},context={'relation':'nearby','names':{}}),country='GE')=={}


def test_canonical_names_use_dictionary_languages_and_only_settlement_has_within_context():
    place={'kind':'settlement','key':'ge:tbilisi','country_iso':'GE','name_ru':'Тбилиси','name_ge':'თბილისი'}
    actual=presentation.canonical_presentation(place)
    assert actual['localized']['ka']['label']=='თბილისი'
    assert actual['context']['relation']=='within'
    checkpoint=presentation.canonical_presentation({**place,'kind':'border_checkpoint'})
    assert 'context' not in checkpoint
    assert 'ka' not in presentation.canonical_presentation({**place,'name_ge':'Тбилиси'})['localized']


@pytest.mark.asyncio
@pytest.mark.parametrize('requested,enabled,key',[(False,True,'fixture-key'),(True,False,'fixture-key'),(True,True,'')])
async def test_provider_requires_both_opt_ins_and_existing_key(monkeypatch,requested,enabled,key):
    monkeypatch.setattr(presentation,'_provider_config',lambda:(enabled,key,'https://provider.invalid/v1'))
    network=AsyncMock(side_effect=AssertionError('Provider must remain unused'))
    monkeypatch.setattr(presentation,'_reverse_snapshots',network)
    assert await presentation.enrich_presentation(41.9,44.6,'GE',requested=requested)=={}
    network.assert_not_called()


@pytest.mark.asyncio
async def test_mock_http_is_bounded_cached_and_retains_only_genuine_language_variants(monkeypatch):
    calls=[]
    async def handler(request):
        calls.append(request)
        language=request.url.params['accept-language']
        return httpx.Response(200,json=snapshots()[0 if language=='ru' else 1])
    real_client=httpx.AsyncClient
    monkeypatch.setattr(presentation,'_provider_config',lambda:(True,'fixture-key','https://provider.invalid/v1'))
    monkeypatch.setattr(presentation.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
    result=await presentation.enrich_presentation(41.904737,44.600335,'GE',label='Продукты',label_mode='auto',requested=True)
    assert result['localized']['ka']['label']=='სურსათი'
    assert result['context']=={'relation':'nearby','names':{'ru':'Дзвели Канда','ka':'ძველი ქანდა'},'country_iso':'GE','source':'locationiq_reverse'}
    assert 'distance_m' not in result['context'],'Feature distance is not distance to settlement'
    assert all(call.url.params['lat']=='41.904737' and call.url.params['lon']=='44.600335' for call in calls)
    assert len(calls)==2
    assert await presentation.enrich_presentation(41.904737,44.600335,'GE',label='Продукты',label_mode='auto',requested=True)==result
    assert len(calls)==2


@pytest.mark.asyncio
async def test_concurrent_identical_points_share_one_lookup_and_cache_is_bounded(monkeypatch):
    calls=0
    async def reverse(*args):
        nonlocal calls
        calls+=1
        await asyncio.sleep(0)
        return snapshots()
    monkeypatch.setattr(presentation,'_provider_config',lambda:(True,'fixture-key','https://provider.invalid/v1'))
    monkeypatch.setattr(presentation,'_reverse_snapshots',reverse)
    monkeypatch.setattr(presentation,'_CACHE_LIMIT',2)
    await asyncio.gather(*(presentation.enrich_presentation(41.9,44.6,'GE',requested=True) for _ in range(5)))
    assert calls==1
    for lat in (41.91,41.92):
        await presentation.enrich_presentation(lat,44.6,'GE',requested=True)
    assert len(presentation._cache)==2


@pytest.mark.asyncio
async def test_new_lookup_rate_budget_and_provider_failure_are_finite(monkeypatch):
    monkeypatch.setattr(presentation,'_provider_config',lambda:(True,'fixture-key','https://provider.invalid/v1'))
    monkeypatch.setattr(presentation,'_MAX_LOOKUPS_PER_MINUTE',1)
    reverse=AsyncMock(side_effect=httpx.ReadTimeout('fixture timeout'))
    monkeypatch.setattr(presentation,'_reverse_snapshots',reverse)
    assert await presentation.enrich_presentation(41.9,44.6,'GE',requested=True)=={}
    assert await presentation.enrich_presentation(41.91,44.6,'GE',requested=True)=={}
    assert reverse.await_count==1


def test_wrong_country_unrelated_object_and_custom_names_cannot_be_relabelled():
    rows=snapshots()
    assert presentation._snapshot_presentation(rows,'RU','Продукты','auto')=={}
    unrelated=presentation._snapshot_presentation(rows,'GE','Монастырь','auto')
    custom=presentation._snapshot_presentation(rows,'GE','Продукты','custom')
    assert 'label' not in unrelated['localized']['ka']
    assert 'label' not in custom['localized']['ka']
    assert 'lat' not in custom and 'lon' not in custom and 'settlement_key' not in custom


def test_missing_georgian_stays_missing_and_region_fallback_is_explicit():
    rows=snapshots()
    rows[1]=deepcopy(rows[0])
    result=presentation._snapshot_presentation(rows,'GE','Монастырь','auto')
    assert 'ka' not in result['localized'] and 'ka' not in result['context']['names']
    for row in rows:
        row['address'].pop('village',None)
    assert presentation._snapshot_presentation(rows,'GE','Монастырь','auto')['context']['relation']=='region'


def test_language_responses_for_different_features_are_not_combined():
    rows=snapshots()
    rows[1]['osm_id']=999
    result=presentation._snapshot_presentation(rows,'GE','Продукты','auto')
    assert 'ka' not in result['localized'] and 'ka' not in result['context']['names']


def test_missing_feature_identity_cannot_link_translated_poi_or_combine_language_contexts():
    rows=snapshots()
    for row in rows:
        row.pop('osm_id')
        row.pop('osm_type')
    result=presentation._snapshot_presentation(rows,'GE','Продукты','auto')
    assert 'label' not in result['localized']['ru']
    assert 'ka' not in result['localized'] and 'ka' not in result['context']['names']
