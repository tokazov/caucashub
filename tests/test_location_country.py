"""Actual offline geometry tests. No external lookup or database is used."""
import pytest
from app.services import location_country as countries

@pytest.mark.parametrize('lat,lon,expected',[
    (41.6938,44.8015,'GE'),(41.6424,41.6355,'GE'),(41.63,41.64,'GE'),
    (42.15,41.67,'GE'),(42.2679,42.6975,'GE'),(40.1872,44.5152,'AM'),
    (43.0241,44.6814,'RU'),(41.0082,28.9784,'TR'),(51.5074,-0.1278,'GB'),
    # Dariali checkpoint is also ~660 m inside the finer GE boundary.
    (42.7403055,44.6266141,'GE'),(0,0,None),(-70,0,None),
    (True,44,None),(41,False,None),(float('nan'),44,None),(41,float('inf'),None),
    (91,44,None),(41,181,None),('bad',44,None),(None,44,None),
])
def test_real_country_geometry_and_ambiguous_border(lat,lon,expected):
    assert countries.resolve_country(lat,lon)==expected


def test_polygon_holes_are_not_inside_country():
    rings=[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[4,4],[6,4],[6,6],[4,6],[4,4]]]
    assert countries._in_polygon(2,2,rings)
    assert not countries._in_polygon(5,5,rings)


def test_near_second_country_refuses_a_country_guess(monkeypatch):
    first=[[[0,0],[1,0],[1,1],[0,1],[0,0]]]
    second=[[[1,0],[2,0],[2,1],[1,1],[1,0]]]
    monkeypatch.setattr(countries,'_countries',lambda:(('AA',(((0,0,1,1),first),)),('BB',(((1,0,2,1),second),))))
    assert countries.resolve_country(.5,.5)=='AA'
    assert countries.resolve_country(.5,.9999) is None
    assert countries.resolve_country(.5,1.0001) is None


def test_overlapping_countries_are_ambiguous(monkeypatch):
    rings=[[[0,0],[1,0],[1,1],[0,1],[0,0]]]
    monkeypatch.setattr(countries,'_countries',lambda:(('AA',(((0,0,1,1),rings),)),('BB',(((0,0,1,1),rings),))))
    assert countries.resolve_country(.5,.5) is None


def test_real_checkpoint_catalogue_keeps_border_sides_and_source_coordinates():
    import json
    from pathlib import Path
    file=Path(countries.__file__).with_name('location_catalog.json')
    rows=json.loads(file.read_text(encoding='utf-8'))['locations']
    by_key={row['key']:row for row in rows}
    assert by_key['ge:dariali-checkpoint']['country_iso']=='GE'
    assert by_key['ru:upper-lars-checkpoint']['country_iso']=='RU'
    assert len(by_key)==len(rows)==4
    for row in rows:
        assert row['sources'] and row['aliases']
        assert row['kind']=='border_checkpoint'
        # Catalogue source coordinates must at least lie in their stated country;
        # known objects can use verified source coordinates even in guarded areas.
        assert any(iso==row['country_iso'] and any(countries._within(box,row['lon'],row['lat'])
                   and countries._in_polygon(row['lon'],row['lat'],rings) for box,rings in polys)
                   for iso,polys in countries._countries())


@pytest.mark.parametrize('lat,lon,expected',[
    # Exact user-selected monastery-approach point; no checkpoint snapping.
    (42.738287,44.628916,'GE'),
    # Publicly described Dariali monastery location, deeper inside GE.
    (42.735644,44.631244,'GE'),
    # Exact native Yandex POI coordinates, preserved without catalogue snapping.
    (42.735488913518935,44.63132098317131,'GE'),
    # Unique GE, about 427 m inside the finer boundary: remains ambiguous.
    (42.742116,44.629154,None),
    # Unique GE, about 512 m inside: finer-country evidence is sufficient.
    (42.7413502,44.6291064,'GE'),
    # Both coarse RU and finer GE contain this point: overlap still wins.
    (42.7428818,44.6292016,None),
    # Russian-side points keep the original global 2 km neighbour guard.
    (42.7482424,44.6295348,None),(42.7681775,44.6316296,'RU'),
])
def test_dariali_finer_georgia_interior_preserves_border_ambiguity(lat,lon,expected):
    assert countries.resolve_country(lat,lon)==expected


def _adjacent_georgia_russia(monkeypatch):
    ge=[[[0,0],[1,0],[1,1],[0,1],[0,0]]]
    ru=[[[1,0],[2,0],[2,1],[1,1],[1,0]]]
    monkeypatch.setattr(countries,'_countries',lambda:(
        ('GE',(((0,0,1,1),ge),)),('RU',(((1,0,2,1),ru),))))


@pytest.mark.parametrize('distance,expected',[(499,None),(500,None),(501,'GE'),(1999,'GE')])
def test_finer_georgia_exception_requires_more_than_500_metres(monkeypatch,distance,expected):
    import math
    _adjacent_georgia_russia(monkeypatch)
    scale=countries._METRES_PER_DEGREE*math.cos(math.radians(.5))
    assert countries.resolve_country(.5,1-distance/scale)==expected


@pytest.mark.parametrize('distance,expected',[(499,None),(501,None),(1999,None),(2001,'RU')])
def test_foreign_side_retains_two_kilometre_guard(monkeypatch,distance,expected):
    import math
    _adjacent_georgia_russia(monkeypatch)
    scale=countries._METRES_PER_DEGREE*math.cos(math.radians(.5))
    assert countries.resolve_country(.5,1+distance/scale)==expected


def test_foreign_overlap_beats_deep_georgia_interior(monkeypatch):
    rings=[[[0,0],[1,0],[1,1],[0,1],[0,0]]]
    monkeypatch.setattr(countries,'_countries',lambda:(
        ('GE',(((0,0,1,1),rings),)),('RU',(((0,0,1,1),rings),))))
    assert countries._high_resolution_georgia_interior(.5,.5)
    assert countries.resolve_country(.5,.5) is None


def test_georgia_coast_without_foreign_neighbour_keeps_existing_behavior(monkeypatch):
    _adjacent_georgia_russia(monkeypatch)
    assert countries.resolve_country(.5,.0001)=='GE'
