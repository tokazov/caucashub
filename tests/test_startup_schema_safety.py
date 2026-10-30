"""Startup cannot hide schema failures. Isolated SQLite/explicit test PostgreSQL."""
import asyncio
import json
import os
import re
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app import main as application
from app.services import schema_readiness as readiness
from scripts import prepare_loading_period as release


@pytest_asyncio.fixture(params=['sqlite',pytest.param('postgresql',marks=pytest.mark.skipif(
    not os.environ.get('TEST_POSTGRES_URL'),reason='requires isolated test PostgreSQL'))])
async def safety_database(request,tmp_path):
    bootstrap=None
    schema='test_startup_safety_'+uuid4().hex
    assert re.fullmatch(r'test_startup_safety_[a-f0-9]{32}',schema)
    if request.param=='postgresql':
        url=os.environ['TEST_POSTGRES_URL']
        for prefix in ('postgresql://','postgres://'):
            if url.startswith(prefix):url='postgresql+asyncpg://'+url[len(prefix):];break
        bootstrap=create_async_engine(url)
        async with bootstrap.begin() as connection:
            await connection.execute(text('CREATE SCHEMA "'+schema+'"'))
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'10000'}})
    else:
        engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'startup-safety.db'))
    try:
        yield engine
    finally:
        await engine.dispose()
        if bootstrap:
            async with bootstrap.begin() as connection:
                await connection.execute(text('DROP SCHEMA "'+schema+'" CASCADE'))
            await bootstrap.dispose()


async def provision(engine):
    await release.prepare_schema(engine,verify_application=True,bootstrap_empty=True)
    async with engine.begin() as connection:
        await connection.execute(text("INSERT INTO users (id,email,hashed_password,company_name,is_demo,is_deleted,password_version) "
                                      "VALUES (1,'sentinel@example.test','unused','Existing customer',false,false,0)"))
        await connection.execute(text("INSERT INTO loads (id,user_id,from_city,to_city,weight_kg,truck_type,load_date,is_demo) "
                                      "VALUES (1,1,'Тбилиси','Батуми',1000,'tent','2026-01-01',false)"))
        await connection.execute(text("INSERT INTO cities (id,name_ru,country_iso) VALUES (1,'Тбилиси','GE')"))


async def sentinels(engine):
    async with engine.connect() as connection:
        return ((await connection.execute(text('SELECT id,company_name FROM users'))).all(),
                (await connection.execute(text('SELECT id,from_city,to_city FROM loads'))).all())


@pytest.fixture
def application_hooks(monkeypatch):
    original_state=getattr(application.app.state,'schema_ready',False)
    original_cache=dict(application._smoke_cache)
    monkeypatch.setenv('NOTIFICATIONS_WORKER_ENABLED','0')
    async def idle():await asyncio.Event().wait()
    monkeypatch.setattr(application,'_smoke_loop',idle)
    monkeypatch.setattr(application,'_idempotency_cleanup_loop',idle)
    def bind(engine):
        monkeypatch.setattr(application,'engine',engine)
        monkeypatch.setattr(database,'engine',engine)
        monkeypatch.setattr(database,'AsyncSessionLocal',async_sessionmaker(engine,expire_on_commit=False))
    yield bind
    application.app.state.schema_ready=original_state
    application._smoke_cache.clear();application._smoke_cache.update(original_cache)


@pytest.mark.asyncio
async def test_startup_and_health_use_read_only_checks_and_preserve_records(safety_database,application_hooks):
    engine=safety_database
    await provision(engine)
    before=await sentinels(engine)
    statements=[]
    event.listen(engine.sync_engine,'before_cursor_execute',lambda conn,cursor,statement,*args:statements.append(statement))
    application_hooks(engine)
    async with application.lifespan(application.app):
        result=await application.health()
        assert isinstance(result,dict) and result['status']=='healthy' and result['checks']['schema']=='ok'
        assert (await application.health_legacy())['status']=='healthy'
        assert not any('warming_up' in str(value) for value in result['checks'].values())
    assert application.app.state.schema_ready is False
    assert await sentinels(engine)==before
    assert statements and all(statement.lstrip().upper().startswith('SELECT') for statement in statements)


@pytest.mark.asyncio
async def test_missing_user_column_blocks_startup_and_never_reports_healthy(safety_database,application_hooks,capsys):
    engine=safety_database
    await provision(engine);before=await sentinels(engine)
    async with engine.begin() as connection:
        await connection.execute(text('ALTER TABLE users DROP COLUMN password_version'))
    application_hooks(engine)
    application._smoke_cache['checks']={'loads':'ok','geocoder':'ok','dicts':'ok'}
    with pytest.raises(readiness.SchemaNotReady,match='users'):
        async with application.lifespan(application.app):pytest.fail('Failed schema must not serve traffic')
    assert application.app.state.schema_ready is False
    for result in (await application.health(),await application.health_legacy()):
        assert result.status_code==503 and json.loads(result.body)['status']=='unhealthy'
    assert 'Required application schema verified' not in capsys.readouterr().out
    assert await sentinels(engine)==before


@pytest.mark.asyncio
async def test_runtime_missing_column_fails_health_even_after_successful_start(safety_database,application_hooks):
    engine=safety_database
    await provision(engine);application_hooks(engine)
    async with application.lifespan(application.app):
        async with engine.begin() as connection:
            await connection.execute(text('ALTER TABLE users DROP COLUMN password_version'))
        result=await application.health()
        assert result.status_code==503
        assert 'schema' in json.loads(result.body)['failed_checks']


@pytest.mark.asyncio
async def test_empty_database_requires_explicit_bootstrap_and_existing_schema_is_never_recreated(safety_database):
    engine=safety_database
    with pytest.raises(Exception):await release.prepare_schema(engine,verify_application=True)
    await provision(engine)
    before=await sentinels(engine)
    with pytest.raises(readiness.SchemaNotReady,match='tables already exist'):
        await release.prepare_schema(engine,verify_application=True,bootstrap_empty=True)
    await release.prepare_schema(engine,verify_application=True)
    assert await sentinels(engine)==before


@pytest.mark.asyncio
async def test_predeploy_failure_rolls_back_changes_and_keeps_all_customer_records(safety_database,monkeypatch):
    engine=safety_database
    await provision(engine);before=await sentinels(engine)
    async with engine.begin() as connection:
        await connection.execute(text('ALTER TABLE loads DROP COLUMN load_date_end'))
    def fail(connection):
        connection.execute(text("UPDATE users SET company_name='MUST ROLLBACK' WHERE id=1"))
        raise RuntimeError('Injected migration failure')
    monkeypatch.setattr(release,'prepare_notifications',fail)
    with pytest.raises(RuntimeError,match='Injected migration failure'):
        await release.prepare_schema(engine,verify_application=True)
    assert await sentinels(engine)==before
    if engine.dialect.name=='postgresql':
        async with engine.connect() as connection:
            columns=await connection.run_sync(lambda sync:{item['name'] for item in inspect(sync).get_columns('loads')})
            assert 'load_date_end' not in columns,'PostgreSQL must roll back the earlier additive DDL too'


@pytest.mark.asyncio
async def test_full_predeploy_verification_rejects_uncovered_legacy_drift(safety_database):
    engine=safety_database
    await provision(engine);before=await sentinels(engine)
    async with engine.begin() as connection:
        await connection.execute(text('ALTER TABLE users DROP COLUMN company_name'))
    with pytest.raises(readiness.SchemaNotReady,match='users'):
        await release.prepare_schema(engine,verify_application=True)
    async with engine.connect() as connection:
        assert (await connection.execute(text('SELECT id FROM users'))).all()==[(1,)]
        assert (await connection.execute(text('SELECT id,from_city,to_city FROM loads'))).all()==before[1]


@pytest.mark.asyncio
async def test_postgres_wider_legacy_type_is_never_narrowed_on_start(safety_database,application_hooks):
    engine=safety_database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL enforces varchar width')
    await provision(engine)
    async with engine.begin() as connection:
        await connection.execute(text('ALTER TABLE status_changes ALTER COLUMN entity_type TYPE VARCHAR(120)'))
        await connection.execute(text("INSERT INTO status_changes (entity_type,entity_id,to_status) VALUES (:value,1,'active')"),{'value':'x'*80})
    # Simulate a newly started API process after an earlier schema change.
    # asyncpg otherwise reuses provision()'s prepared SELECT with the old row
    # type; that driver-cache failure is unrelated to legacy type preservation.
    await engine.dispose()
    application_hooks(engine)
    async with application.lifespan(application.app):pass
    async with engine.connect() as connection:
        assert (await connection.execute(text('SELECT entity_type FROM status_changes'))).scalar_one()=='x'*80
        width=await connection.run_sync(lambda sync:next(item for item in inspect(sync).get_columns('status_changes') if item['name']=='entity_type')['type'].length)
        assert width==120


@pytest.mark.asyncio
async def test_postgres_missing_native_enum_value_is_not_silently_accepted(safety_database):
    engine=safety_database
    if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL native enum write constraint')
    await provision(engine);before=await sentinels(engine)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TYPE test_short_userplan AS ENUM ('free','standard','pro')"))
        await connection.execute(text('ALTER TABLE users ALTER COLUMN plan TYPE test_short_userplan USING plan::text::test_short_userplan'))
    # The deployment's new process has no cached SELECT for the previous enum.
    # Close setup connections so the assertion checks native enum compatibility.
    await engine.dispose()
    with pytest.raises(readiness.SchemaNotReady,match='users.plan'):
        await readiness.verify_application_schema(engine)
    assert await sentinels(engine)==before


def test_cli_failure_is_nonzero_and_does_not_print_success_or_driver_secrets(monkeypatch,capsys):
    monkeypatch.setattr('sys.argv',['prepare_loading_period'])
    monkeypatch.setattr(release,'run',AsyncMock(side_effect=RuntimeError('sensitive-driver-detail')))
    assert release.main()==1
    output=capsys.readouterr()
    assert 'schema ready' not in output.out and 'sensitive-driver-detail' not in output.err


@pytest.mark.asyncio
async def test_production_cli_path_always_requires_full_application_verification(monkeypatch):
    fake=type('DisposableEngine',(),{'dispose':AsyncMock()})()
    monkeypatch.setattr(database,'engine',fake)
    prepare=AsyncMock()
    monkeypatch.setattr(release,'prepare_schema',prepare)
    await release.run()
    prepare.assert_awaited_once_with(fake,verify_application=True,bootstrap_empty=False)
