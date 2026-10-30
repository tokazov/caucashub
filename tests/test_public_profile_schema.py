"""027 consent migration on disposable SQLite and unique CI PostgreSQL schemas."""
import pytest
from sqlalchemy import Boolean, inspect, text

from scripts import prepare_loading_period as release
from tests.test_deal_review_schema import review_database  # noqa: F401


@pytest.mark.asyncio
async def test_027_default_private_repeatable_and_never_rewrites_existing_texts(review_database):
    async with review_database.begin() as connection:
        await connection.run_sync(release.prepare_deal_reviews)
        await connection.execute(text("INSERT INTO deal_reviews (id,deal_id,rater_id,recipient_id,score,comment) "
                                      "VALUES (1,1,1,2,4,'Private legacy comment')"))
        await connection.run_sync(release.prepare_public_review_visibility)
        await connection.run_sync(release.prepare_public_review_visibility)
        assert (await connection.execute(text('SELECT score,comment,public_comment FROM deal_reviews WHERE id=1'))).one()==(4,'Private legacy comment',False)
        await connection.execute(text("INSERT INTO deal_reviews (id,deal_id,rater_id,recipient_id,score,comment) "
                                      "VALUES (2,1,2,1,5,'Default remains private')"))
        await connection.execute(text('UPDATE deal_reviews SET public_comment=true WHERE id=1'))
        await connection.run_sync(release.prepare_public_review_visibility)
        assert (await connection.execute(text('SELECT id,public_comment FROM deal_reviews ORDER BY id'))).all()==[(1,True),(2,False)]
        column=await connection.run_sync(lambda sync: next(item for item in inspect(sync).get_columns('deal_reviews') if item['name']=='public_comment'))
        assert isinstance(column['type'],Boolean) and column['nullable'] is False and column['default'] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('definition',["BOOLEAN NULL DEFAULT false","BOOLEAN NOT NULL DEFAULT true","TEXT NOT NULL DEFAULT 'false'"])
async def test_027_gate_rejects_unsafe_existing_consent_column(review_database,definition):
    async with review_database.begin() as connection:
        await connection.run_sync(release.prepare_deal_reviews)
        await connection.execute(text('ALTER TABLE deal_reviews ADD COLUMN public_comment '+definition))
        with pytest.raises(RuntimeError,match='public_comment'):
            await connection.run_sync(release.prepare_public_review_visibility)


@pytest.mark.asyncio
async def test_full_gate_requires_consent_column_even_if_027_step_is_skipped(review_database,monkeypatch):
    monkeypatch.setattr(release,'prepare_public_review_visibility',lambda connection:None)
    with pytest.raises(Exception,match='public_comment'):
        await release.prepare_schema(review_database)
