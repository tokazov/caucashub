"""028 is nullable, repeatable and never fabricates document-party names."""
import pytest
from sqlalchemy import DateTime, String, inspect, text
from scripts import prepare_loading_period as release
from tests.test_deal_review_schema import review_database  # noqa: F401


@pytest.mark.asyncio
async def test_028_repeatable_nullable_no_backfill_and_preserves_owner_input(review_database):
    async with review_database.begin() as connection:
        await connection.execute(text('ALTER TABLE users ADD COLUMN company_name TEXT'))
        await connection.execute(text("UPDATE users SET company_name='Mixed Registration Name' WHERE id=1"))
        for _ in range(2):await connection.run_sync(release.prepare_document_names)
        rows=(await connection.execute(text('SELECT legal_name_ka,legal_name_ka_confirmed_at FROM users ORDER BY id'))).all()
        assert rows==[(None,None),(None,None)]
        await connection.execute(text("UPDATE users SET legal_name_ka=:name,legal_name_ka_confirmed_at=CURRENT_TIMESTAMP WHERE id=1"),{'name':'შპს ქართული სახელი'})
        await connection.run_sync(release.prepare_document_names)
        row=(await connection.execute(text('SELECT legal_name_ka,legal_name_ka_confirmed_at FROM users WHERE id=1'))).one()
        assert row.legal_name_ka=='შპს ქართული სახელი' and row.legal_name_ka_confirmed_at
        columns=await connection.run_sync(lambda sync:{item['name']:item for item in inspect(sync).get_columns('users')})
        assert isinstance(columns['legal_name_ka']['type'],String) and columns['legal_name_ka']['type'].length==255
        assert isinstance(columns['legal_name_ka_confirmed_at']['type'],DateTime)
        if review_database.dialect.name=='postgresql':assert columns['legal_name_ka_confirmed_at']['type'].timezone
        assert all(columns[name]['nullable'] and columns[name]['default'] is None for name in ('legal_name_ka','legal_name_ka_confirmed_at'))
    await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        retained=(await connection.execute(text('SELECT company_name,legal_name_ka,legal_name_ka_confirmed_at FROM users WHERE id=1'))).one()
        assert retained.company_name=='Mixed Registration Name' and retained.legal_name_ka=='შპს ქართული სახელი' and retained.legal_name_ka_confirmed_at


@pytest.mark.asyncio
@pytest.mark.parametrize('definition',["VARCHAR(50) NULL","VARCHAR(255) NOT NULL DEFAULT ''","TEXT NULL","VARCHAR(255) NULL DEFAULT ''"])
async def test_028_gate_rejects_unsafe_or_short_name_columns(review_database,definition):
    async with review_database.begin() as connection:
        await connection.execute(text('ALTER TABLE users ADD COLUMN legal_name_ka '+definition))
        with pytest.raises(RuntimeError,match='legal_name_ka'):
            await connection.run_sync(release.prepare_document_names)


@pytest.mark.asyncio
@pytest.mark.parametrize('definition',["VARCHAR(255) NULL","TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP","TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"])
async def test_028_gate_rejects_unsafe_confirmation_columns(review_database,definition):
    async with review_database.begin() as connection:
        # SQLite cannot ALTER a nonempty table with a nonconstant default;
        # use a literal timestamp to reach the actual release-gate assertion.
        # PostgreSQL retains CURRENT_TIMESTAMP so that native default is tested.
        if review_database.dialect.name=='sqlite':
            definition=definition.replace('CURRENT_TIMESTAMP',"'2026-01-01 00:00:00'")
        await connection.execute(text('ALTER TABLE users ADD COLUMN legal_name_ka_confirmed_at '+definition))
        with pytest.raises(RuntimeError,match='legal_name_ka_confirmed_at'):
            await connection.run_sync(release.prepare_document_names)


@pytest.mark.asyncio
async def test_028_postgres_rejects_confirmation_without_timezone(review_database):
    if review_database.dialect.name!='postgresql':pytest.skip('PostgreSQL timezone storage type')
    async with review_database.begin() as connection:
        await connection.execute(text('ALTER TABLE users ADD COLUMN legal_name_ka_confirmed_at TIMESTAMP WITHOUT TIME ZONE NULL'))
        with pytest.raises(RuntimeError,match='legal_name_ka_confirmed_at'):
            await connection.run_sync(release.prepare_document_names)


@pytest.mark.asyncio
async def test_028_full_gate_rejects_noop_document_step(review_database,monkeypatch):
    monkeypatch.setattr(release,'prepare_document_names',lambda connection:None)
    with pytest.raises(Exception,match='legal_name_ka'):
        await release.prepare_schema(review_database)
