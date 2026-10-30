"""Actual overlapping participant downloads use one PostgreSQL-issued bundle."""
import asyncio
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.models.deal_act_archive import DealActArchive
from app.routers import deals
from tests.test_publication_journeys import journey  # noqa: F401
from tests.test_document_requisites import documents, confirm_names  # noqa: F401
from tests.test_deal_completion_http import complete


def overlapping_downloads(monkeypatch):
    original = deals._locked_deal
    first_holds_lock, second_started = asyncio.Event(), asyncio.Event()
    calls = 0

    async def coordinated_lock(db, deal_id, user_id):
        nonlocal calls
        calls += 1
        ordinal = calls
        if ordinal == 2:
            second_started.set()
        result = await original(db, deal_id, user_id)
        if ordinal == 1:
            first_holds_lock.set()
            await asyncio.wait_for(second_started.wait(), timeout=5)
        return result

    monkeypatch.setattr(deals, '_locked_deal', coordinated_lock)
    return first_holds_lock


async def download(context, deal_id, role, language):
    return await context['client'].get(f'/api/deals/{deal_id}/act.pdf?lang={language}',
                                       headers=context['headers'][role])


@pytest.mark.asyncio
async def test_postgres_parallel_first_issue_stores_one_bundle_and_replays_both_languages(documents, monkeypatch):
    if documents['engine'].dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row-lock serialization; SQLite has no FOR UPDATE')
    deal_id, _ = await complete(documents, 'cargo')
    await confirm_names(documents)
    rendered = Mock(wraps=deals.generate_act_pdf)
    monkeypatch.setattr(deals, 'generate_act_pdf', rendered)
    barrier = overlapping_downloads(monkeypatch)
    first = asyncio.create_task(download(documents, deal_id, 'shipper', 'ru'))
    await asyncio.wait_for(barrier.wait(), timeout=5)
    second = asyncio.create_task(download(documents, deal_id, 'carrier', 'ge'))
    replies = await asyncio.wait_for(asyncio.gather(first, second), timeout=20)
    assert [reply.status_code for reply in replies] == [200, 200], [reply.text for reply in replies]
    assert rendered.call_count == 2, 'Only the first request renders both saved language variants'
    async with documents['sessions']() as db:
        assert (await db.execute(select(func.count()).select_from(DealActArchive))).scalar_one() == 1
        stored = await db.get(DealActArchive, deal_id)
        original_payload = stored.payload_sha256
        assert replies[0].content == stored.ru_pdf and replies[1].content == stored.ge_pdf
        issue_stamp = replies[0].headers['x-act-issued-at']
        assert replies[1].headers['x-act-issued-at'] == issue_stamp
    monkeypatch.setattr(deals, 'generate_act_pdf', Mock(side_effect=RuntimeError('Must never regenerate issued act')))
    again = await asyncio.gather(download(documents, deal_id, 'carrier', 'ru'),
                                 download(documents, deal_id, 'shipper', 'ge'))
    assert [reply.status_code for reply in again] == [200, 200]
    assert [reply.content for reply in again] == [reply.content for reply in replies]
    async with documents['sessions']() as db:
        assert (await db.get(DealActArchive, deal_id)).payload_sha256 == original_payload
        assert (await db.execute(select(func.count()).select_from(DealActArchive))).scalar_one() == 1


@pytest.mark.asyncio
async def test_postgres_failed_first_bundle_releases_lock_for_other_participant(documents, monkeypatch):
    if documents['engine'].dialect.name != 'postgresql':
        pytest.skip('PostgreSQL concurrent rollback proof')
    deal_id, _ = await complete(documents, 'transport')
    await confirm_names(documents)
    original = deals.generate_act_pdf
    failed = False

    def fail_once(data):
        nonlocal failed
        if data['lang'] == 'ge' and not failed:
            failed = True
            raise RuntimeError('Synthetic second-language failure')
        return original(data)

    monkeypatch.setattr(deals, 'generate_act_pdf', fail_once)
    barrier = overlapping_downloads(monkeypatch)
    first = asyncio.create_task(download(documents, deal_id, 'shipper', 'ru'))
    await asyncio.wait_for(barrier.wait(), timeout=5)
    second = asyncio.create_task(download(documents, deal_id, 'carrier', 'ge'))
    replies = await asyncio.wait_for(asyncio.gather(first, second), timeout=20)
    assert [reply.status_code for reply in replies] == [500, 200], [reply.status_code for reply in replies]
    async with documents['sessions']() as db:
        assert (await db.execute(select(func.count()).select_from(DealActArchive))).scalar_one() == 1
        stored = await db.get(DealActArchive, deal_id)
        assert replies[1].content == stored.ge_pdf and stored.ru_pdf.startswith(b'%PDF-')
    retry = await download(documents, deal_id, 'shipper', 'ru')
    assert retry.status_code == 200 and retry.content == stored.ru_pdf
