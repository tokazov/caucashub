"""Release ordering rejects an old/failed API and incomplete location schema."""
import pytest
from scripts.wait_for_api_release import matching_release

SHA = 'a' * 40
PLACE = {'results': [{'key': 'ge:dariali-checkpoint', 'kind': 'border_checkpoint', 'country_iso': 'GE'}]}

@pytest.mark.parametrize('health,places,expected',[
    ({'status':'healthy','release':SHA}, PLACE, True),
    ({'status':'healthy','release':'b'*40}, PLACE, False),
    ({'status':'unhealthy','release':SHA}, PLACE, False),
    ({'status':'healthy'}, PLACE, False),
    ({'status':'healthy','release':SHA}, {'results':[]}, False),
    ({'status':'healthy','release':SHA}, {'results':[{'key':'ge:dariali-checkpoint','kind':'point','country_iso':'GE'}]}, False),
    ({'status':'healthy','release':SHA}, {'results':[{'key':'ge:dariali-checkpoint','kind':'border_checkpoint','country_iso':'RU'}]}, False),
])
def test_frontend_waits_for_matching_typed_api(health,places,expected):
    assert matching_release(health,places,SHA) is expected


@pytest.mark.parametrize('cargo,offers,expected',[
    ({'loads':[]},{'offers':[]},True),
    ({'loads':[{'from_location':None,'to_location':None}]},
     {'offers':[{'from_location':None,'to_location':None,'last_confirmed_at':None}]},True),
    ({'loads':[{}]},{'offers':[]},False),
    ({'loads':[]},{'offers':[{'from_location':None,'to_location':None}]},False),
    ({'loads':None},{'offers':[]},False),
])
def test_real_listing_reads_must_have_the_new_nullable_fields(cargo,offers,expected):
    from scripts.wait_for_api_release import listings_ready
    assert listings_ready(cargo,offers) is expected
