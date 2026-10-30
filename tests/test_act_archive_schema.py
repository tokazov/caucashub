"""029 is additive and rejects archive drift without changing issued rows."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON,
                        LargeBinary, MetaData, String, Table, Text, func, inspect, text)
from sqlalchemy.exc import IntegrityError

from scripts import prepare_loading_period as release
from tests.test_deal_review_schema import review_database  # noqa: F401


CHECKS = {
    'ck_deal_act_archive_version': 'schema_version = 1',
    'ck_deal_act_archive_ru_pdf': 'length(ru_pdf) > 0',
    'ck_deal_act_archive_ge_pdf': 'length(ge_pdf) > 0',
    'ck_deal_act_archive_ru_sha': 'length(ru_sha256) = 64',
    'ck_deal_act_archive_ge_sha': 'length(ge_sha256) = 64',
    'ck_deal_act_archive_payload_sha': 'length(payload_sha256) = 64',
}


def archive_table(connection, drift=None):
    """Only synthetic fixtures; deliberately inconsistent variants reach the gate."""
    metadata = MetaData()
    Table('deals', metadata, autoload_with=connection)
    reference = [] if drift == 'foreign_key' else [ForeignKey(
        'deals.id', ondelete='CASCADE' if drift == 'cascade' else None)]
    columns = [
        Column('deal_id', Integer, *reference, primary_key=drift != 'primary_key', nullable=False),
        Column('schema_version', Integer, nullable=False, server_default='2' if drift == 'version_default' else '1'),
        Column('issued_at', DateTime(timezone=drift != 'naive_timestamp'), nullable=False,
               server_default=text("'2000-01-01 00:00:00'") if drift == 'issue_default' else func.now()),
        Column('payload', Text if drift == 'payload_type' else JSON,
               nullable=drift == 'payload_nullable',
               server_default=text("'{}'") if drift == 'payload_default' else None),
        Column('payload_sha256', String(64), nullable=False),
        Column('ru_pdf', Text if drift == 'pdf_type' else LargeBinary, nullable=False),
        Column('ge_pdf', LargeBinary, nullable=False),
        Column('ru_sha256', String(32 if drift == 'sha_width' else 64), nullable=False),
        Column('ge_sha256', String(64), nullable=False),
    ]
    if drift == 'missing_column':
        columns = [column for column in columns if column.name != 'payload']
    constraints = [CheckConstraint(
        'schema_version = 2' if drift == 'check_expression' and name.endswith('_version') else expression,
        name=name) for name, expression in CHECKS.items()
        if not (drift == 'missing_check' and name.endswith('_ru_pdf'))]
    table = Table('deal_act_archives', metadata, *columns, *constraints)
    table.create(connection)
    return table


def archive_values(**changes):
    values = dict(deal_id=1, schema_version=1, payload={'synthetic': True},
                  payload_sha256='a' * 64, ru_pdf=b'%PDF-synthetic-ru', ge_pdf=b'%PDF-synthetic-ge',
                  ru_sha256='b' * 64, ge_sha256='c' * 64)
    values.update(changes)
    return values


@pytest.mark.asyncio
async def test_029_repeatable_keeps_existing_records_and_never_backfills_acts(review_database):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.begin() as connection:
        assert (await connection.execute(text('SELECT COUNT(*) FROM deal_act_archives'))).scalar_one() == 0
        table = await connection.run_sync(lambda sync: Table(
            'deal_act_archives', MetaData(), autoload_with=sync))
        await connection.execute(table.insert().values(**archive_values()))
    await release.prepare_schema(engine)
    await release.prepare_schema(engine)
    async with engine.connect() as connection:
        row = (await connection.execute(table.select())).one()
        assert row.deal_id == 1 and row.payload == {'synthetic': True}
        assert bytes(row.ru_pdf) == b'%PDF-synthetic-ru' and bytes(row.ge_pdf) == b'%PDF-synthetic-ge'
        assert row.ru_sha256 == 'b' * 64 and row.ge_sha256 == 'c' * 64 and row.issued_at
        assert (await connection.execute(text('SELECT id FROM deals ORDER BY id'))).all() == [(1,), (2,)]
        assert (await connection.execute(text('SELECT id FROM users ORDER BY id'))).all() == [(1,), (2,)]
        columns = await connection.run_sync(lambda sync: inspect(sync).get_columns('deal_act_archives'))
        assert len(columns) == 9 and all(not column['nullable'] for column in columns)
        if engine.dialect.name == 'postgresql':
            assert next(column for column in columns if column['name'] == 'issued_at')['type'].timezone


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', [
    'foreign_key', 'cascade', 'primary_key', 'payload_type', 'pdf_type', 'payload_nullable',
    'payload_default', 'sha_width', 'version_default', 'issue_default', 'missing_column',
    'check_expression', 'missing_check', 'naive_timestamp',
])
async def test_029_gate_rejects_existing_drift_without_repair_or_record_changes(review_database, drift):
    if drift == 'naive_timestamp' and review_database.dialect.name == 'sqlite':
        pytest.skip('SQLite has no native timezone storage distinction')
    async with review_database.begin() as connection:
        await connection.run_sync(lambda sync: archive_table(sync, drift))
    with pytest.raises(RuntimeError, match='Act archive schema'):
        await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        assert (await connection.execute(text('SELECT id FROM deals ORDER BY id'))).all() == [(1,), (2,)]
        assert (await connection.execute(text('SELECT COUNT(*) FROM deal_act_archives'))).scalar_one() == 0
        columns = await connection.run_sync(lambda sync: inspect(sync).get_columns('deal_act_archives'))
        if drift == 'missing_column':
            assert 'payload' not in {column['name'] for column in columns}


@pytest.mark.asyncio
async def test_029_archive_gate_cannot_be_silently_skipped(review_database, monkeypatch):
    monkeypatch.setattr(release, 'prepare_deal_act_archives', lambda connection: None)
    with pytest.raises(Exception, match='deal_act_archives'):
        await release.prepare_schema(review_database)


@pytest.mark.asyncio
async def test_029_archive_constraints_prevent_duplicate_or_empty_bundles(review_database):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.connect() as connection:
        table = await connection.run_sync(lambda sync: Table('deal_act_archives', MetaData(), autoload_with=sync))
    async with engine.begin() as connection:
        await connection.execute(table.insert().values(**archive_values()))
    for change in ({}, {'deal_id': 2, 'schema_version': 2}, {'deal_id': 2, 'ru_pdf': b''},
                   {'deal_id': 2, 'ge_pdf': b''}, {'deal_id': 2, 'ru_sha256': 'x'},
                   {'deal_id': 2, 'ge_sha256': 'x'}, {'deal_id': 2, 'payload_sha256': 'x'}):
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(table.insert().values(**archive_values(**change)))
    async with engine.connect() as connection:
        assert (await connection.execute(text('SELECT COUNT(*) FROM deal_act_archives'))).scalar_one() == 1


@pytest.mark.asyncio
async def test_029_postgres_never_cascades_deal_delete_into_issued_files(review_database):
    if review_database.dialect.name != 'postgresql':
        pytest.skip('Native foreign-key delete restriction')
    await release.prepare_schema(review_database)
    async with review_database.begin() as connection:
        table = await connection.run_sync(lambda sync: Table('deal_act_archives', MetaData(), autoload_with=sync))
        await connection.execute(table.insert().values(**archive_values()))
    with pytest.raises(IntegrityError):
        async with review_database.begin() as connection:
            await connection.execute(text('DELETE FROM deals WHERE id=1'))
    async with review_database.connect() as connection:
        assert (await connection.execute(text('SELECT id FROM deals WHERE id=1'))).scalar_one() == 1
        assert bytes((await connection.execute(table.select())).one().ge_pdf) == b'%PDF-synthetic-ge'


@pytest.mark.asyncio
async def test_029_downgrade_preserves_issued_files(review_database):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.begin() as connection:
        table = await connection.run_sync(lambda sync: Table('deal_act_archives', MetaData(), autoload_with=sync))
        await connection.execute(table.insert().values(**archive_values()))
        def downgrade(sync):
            path = Path(__file__).resolve().parents[1] / 'alembic/versions/029_deal_act_archives.py'
            spec = importlib.util.spec_from_file_location('test_act_archive_downgrade', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            migration.op = Operations(MigrationContext.configure(sync))
            migration.downgrade()
        await connection.run_sync(downgrade)
        assert bytes((await connection.execute(table.select())).one().ru_pdf) == b'%PDF-synthetic-ru'
