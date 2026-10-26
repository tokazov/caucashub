"""Review schema gate: additive, repeatable and unable to bypass constraints."""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from scripts import prepare_loading_period as release


@pytest_asyncio.fixture(params=[
    "sqlite",
    pytest.param("postgresql", marks=pytest.mark.skipif(
        not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")),
])
async def review_database(request, tmp_path):
    bootstrap = None
    schema = "test_review_schema_" + uuid4().hex
    if request.param == "postgresql":
        url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
        bootstrap = create_async_engine(url)
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reviews.db'}")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO users (id) VALUES (1), (2)"))
            await connection.execute(text("INSERT INTO deals (id) VALUES (1), (2)"))
        yield engine
    finally:
        await engine.dispose()
        if bootstrap:
            async with bootstrap.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await bootstrap.dispose()


@pytest.mark.asyncio
async def test_review_gate_repeated_preserves_old_rows_and_new_review(review_database):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.begin() as connection:
        await connection.execute(text(
            "INSERT INTO deal_reviews (id, deal_id, rater_id, recipient_id, score, comment) "
            "VALUES (1, 1, 1, 2, 4, :comment)"),
            {"comment": "Доставлено / დროულად"})
    await release.prepare_schema(engine)
    await release.prepare_schema(engine)
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT COUNT(*) FROM deals"))).scalar_one() == 2
        assert (await connection.execute(text("SELECT COUNT(*) FROM users"))).scalar_one() == 2
        row = (await connection.execute(text(
            "SELECT score, comment, created_at FROM deal_reviews WHERE id = 1"))).one()
        assert row.score == 4 and row.comment == "Доставлено / დროულად" and row.created_at


@pytest.mark.asyncio
@pytest.mark.parametrize("rater,recipient,score", [(1, 2, 5), (2, 1, 0), (2, 1, 6), (2, 2, 4)])
async def test_review_table_enforces_unique_actor_score_and_counterparty(review_database, rater, recipient, score):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.begin() as connection:
        await connection.execute(text(
            "INSERT INTO deal_reviews (id, deal_id, rater_id, recipient_id, score) VALUES (1, 1, 1, 2, 4)"))
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO deal_reviews (id, deal_id, rater_id, recipient_id, score) "
                "VALUES (2, 1, :rater, :recipient, :score)"),
                {"rater": rater, "recipient": recipient, "score": score})
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT COUNT(*) FROM deal_reviews"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_both_participants_and_other_deals_have_independent_unique_keys(review_database):
    engine = review_database
    await release.prepare_schema(engine)
    async with engine.begin() as connection:
        await connection.execute(text(
            "INSERT INTO deal_reviews (id, deal_id, rater_id, recipient_id, score) VALUES "
            "(1, 1, 1, 2, 4), (2, 1, 2, 1, 5), (3, 2, 1, 2, 3)"))
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT COUNT(*) FROM deal_reviews"))).scalar_one() == 3


@pytest.mark.asyncio
async def test_review_gate_fails_when_creation_is_noop(review_database, monkeypatch):
    monkeypatch.setattr(release, "prepare_deal_reviews", lambda connection: None)
    with pytest.raises(Exception, match="deal_reviews"):
        await release.prepare_schema(review_database)


@pytest.mark.asyncio
async def test_review_gate_rejects_partial_table_without_rewriting_it(review_database):
    async with review_database.begin() as connection:
        await connection.execute(text("CREATE TABLE deal_reviews (id INTEGER PRIMARY KEY)"))
        await connection.execute(text("INSERT INTO deal_reviews (id) VALUES (77)"))
    with pytest.raises(RuntimeError, match="missing columns"):
        await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        assert (await connection.execute(text("SELECT id FROM deal_reviews"))).scalar_one() == 77


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["unique", "score", "distinct", "foreign_keys"])
async def test_review_gate_rejects_missing_required_constraints(review_database, missing):
    clauses = [
        ("id SERIAL NOT NULL PRIMARY KEY" if review_database.dialect.name == "postgresql"
         else "id INTEGER NOT NULL PRIMARY KEY"), "deal_id INTEGER NOT NULL",
        "rater_id INTEGER NOT NULL", "recipient_id INTEGER NOT NULL", "score INTEGER NOT NULL",
        "comment TEXT NULL", ("created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
                              if review_database.dialect.name == "postgresql"
                              else "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    if missing != "unique":
        clauses.append("CONSTRAINT uq_deal_reviews_deal_rater UNIQUE (deal_id, rater_id)")
    if missing != "score":
        clauses.append("CONSTRAINT ck_deal_reviews_score_range CHECK (score >= 1 AND score <= 5)")
    if missing != "distinct":
        clauses.append("CONSTRAINT ck_deal_reviews_distinct_people CHECK (rater_id <> recipient_id)")
    if missing != "foreign_keys":
        clauses += ["FOREIGN KEY (deal_id) REFERENCES deals(id)", "FOREIGN KEY (rater_id) REFERENCES users(id)",
                    "FOREIGN KEY (recipient_id) REFERENCES users(id)"]
    async with review_database.begin() as connection:
        await connection.execute(text("CREATE TABLE deal_reviews (\n" + ",\n".join(clauses) + "\n)"))
    # Prove this fixture omits only its target. SQLite's inspector parses CHECK
    # expressions greedily if every constraint is on a single SQL line; real
    # Alembic DDL separates clauses with newlines, as this fixture now does.
    async with review_database.connect() as connection:
        reflected = await connection.run_sync(lambda sync: {
            "checks": inspect(sync).get_check_constraints("deal_reviews"),
            "unique": inspect(sync).get_unique_constraints("deal_reviews"),
            "foreign_keys": inspect(sync).get_foreign_keys("deal_reviews"),
        })
    expressions = {item["name"]: "".join(item["sqltext"].split()).replace("(", "").replace(")", "").lower()
                   for item in reflected["checks"]}
    expected_checks = {
        "ck_deal_reviews_score_range": "score>=1andscore<=5",
        "ck_deal_reviews_distinct_people": "rater_id<>recipient_id",
    }
    if missing == "score":
        del expected_checks["ck_deal_reviews_score_range"]
    if missing == "distinct":
        del expected_checks["ck_deal_reviews_distinct_people"]
    assert expressions == expected_checks
    unique = {tuple(item["column_names"]) for item in reflected["unique"]}
    assert unique == (set() if missing == "unique" else {("deal_id", "rater_id")})
    foreign_keys = {(tuple(item["constrained_columns"]), item["referred_table"])
                    for item in reflected["foreign_keys"]}
    expected_fks = {(("deal_id",), "deals"), (("rater_id",), "users"), (("recipient_id",), "users")}
    assert foreign_keys == (set() if missing == "foreign_keys" else expected_fks)
    expected = {"unique": "unique key", "score": "score range", "distinct": "distinct participant", "foreign_keys": "foreign keys"}[missing]
    with pytest.raises(RuntimeError, match=expected):
        await release.prepare_schema(review_database)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["primary_key", "generated_id", "created_timezone"])
async def test_review_gate_rejects_incompatible_identity_or_timestamp(review_database, drift):
    postgres = review_database.dialect.name == "postgresql"
    if drift == "created_timezone" and not postgres:
        pytest.skip("SQLite timestamps have no timezone storage type")
    identifier = "id SERIAL NOT NULL" if postgres else "id INTEGER NOT NULL"
    created = ("created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
               if postgres else "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP")
    if drift == "generated_id":
        identifier = "id INTEGER NOT NULL" if postgres else "id BIGINT NOT NULL"
    if drift == "created_timezone":
        created = "created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
    clauses = [
        identifier, "deal_id INTEGER NOT NULL", "rater_id INTEGER NOT NULL",
        "recipient_id INTEGER NOT NULL", "score INTEGER NOT NULL", "comment TEXT NULL", created,
        "PRIMARY KEY (deal_id, rater_id)" if drift == "primary_key" else "PRIMARY KEY (id)",
        "CONSTRAINT uq_deal_reviews_deal_rater UNIQUE (deal_id, rater_id)",
        "CONSTRAINT ck_deal_reviews_score_range CHECK (score >= 1 AND score <= 5)",
        "CONSTRAINT ck_deal_reviews_distinct_people CHECK (rater_id <> recipient_id)",
        "FOREIGN KEY (deal_id) REFERENCES deals(id)", "FOREIGN KEY (rater_id) REFERENCES users(id)",
        "FOREIGN KEY (recipient_id) REFERENCES users(id)",
    ]
    async with review_database.begin() as connection:
        await connection.execute(text("CREATE TABLE deal_reviews (\n" + ",\n".join(clauses) + "\n)"))
    expected = {"primary_key": "primary key", "generated_id": "generated ids",
                "created_timezone": "created_at"}[drift]
    with pytest.raises(RuntimeError, match=expected):
        await release.prepare_schema(review_database)
