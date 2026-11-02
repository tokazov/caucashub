"""Disposable SQLite billing simulator, with no production imports or network IO.

BEGIN IMMEDIATE serializes issuance and renewal across connections/processes.
This is an executable sandbox, not a bank adapter or a production DB migration.
"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
from uuid import uuid4

from .catalog import DAY, PROJECTS, products_for

DEMO_CUSTOMERS = {"alice": "Демо Алиса", "bob": "Демо Борис"}
MARKER = "caucashub-isolated-billing-sandbox-v1"
OUTCOMES = frozenset({"paid", "failed", "cancelled", "expired", "refunded"})
EVENT_FIELDS = frozenset({
    "event_id", "order_id", "provider_tx_id", "project",
    "amount_tetri", "currency", "outcome",
})
SCHEMA = (
    "CREATE TABLE sb_meta (marker TEXT NOT NULL)",
    """CREATE TABLE sb_targets (
        project TEXT NOT NULL, id TEXT NOT NULL, customer_id TEXT NOT NULL,
        title TEXT NOT NULL, valid_until REAL NOT NULL,
        PRIMARY KEY (project, id))""",
    """CREATE TABLE sb_orders (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, customer_id TEXT NOT NULL,
        product_code TEXT NOT NULL, product_title TEXT NOT NULL, kind TEXT NOT NULL,
        target_id TEXT, amount_tetri INTEGER NOT NULL CHECK(amount_tetri > 0),
        currency TEXT NOT NULL CHECK(currency = 'GEL'),
        duration_seconds INTEGER NOT NULL CHECK(duration_seconds > 0),
        status TEXT NOT NULL DEFAULT 'pending',
        fulfillment_status TEXT NOT NULL DEFAULT 'not_started',
        fulfillment_error TEXT, created_at REAL NOT NULL, paid_at REAL,
        provider_tx_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
        UNIQUE(project, customer_id, idempotency_key))""",
    """CREATE TABLE sb_grants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL UNIQUE REFERENCES sb_orders(id),
        project TEXT NOT NULL, customer_id TEXT NOT NULL, kind TEXT NOT NULL,
        target_id TEXT, starts_at REAL NOT NULL, ends_at REAL NOT NULL,
        revoked_at REAL, CHECK(ends_at > starts_at))""",
    """CREATE INDEX sb_grants_resource ON sb_grants
        (project, customer_id, kind, target_id, ends_at)""",
    """CREATE TABLE sb_events (
        project TEXT NOT NULL, event_id TEXT NOT NULL,
        order_id TEXT NOT NULL REFERENCES sb_orders(id),
        payload_hash TEXT NOT NULL, outcome TEXT NOT NULL, received_at REAL NOT NULL,
        PRIMARY KEY(project, event_id))""",
)


class BillingError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


class SandboxBilling:
    def __init__(self, db_path, *, project="caucashub", clock=None, signing_secret=None):
        if project not in PROJECTS:
            raise BillingError(400, "unknown_project", "Неизвестный тестовый проект")
        raw_path = str(db_path)
        if "://" in raw_path or not raw_path.endswith(".sandbox.sqlite3"):
            raise BillingError(400, "unsafe_database",
                               "Нужен отдельный файл с окончанием .sandbox.sqlite3")
        self.db_path = Path(db_path).resolve()
        self.project = project
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._secret = signing_secret if signing_secret is not None else secrets.token_bytes(32)
        if not isinstance(self._secret, bytes) or len(self._secret) < 16:
            raise BillingError(400, "weak_test_secret", "Тестовый ключ должен содержать минимум 16 байт")
        self._products = {p.code: p for p in products_for(project)}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sandbox clock must return an aware datetime")
        return value.timestamp()

    def now_iso(self):
        return iso(self._now())

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=20, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._transaction() as db:
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            if tables:
                if "sb_meta" not in tables:
                    raise BillingError(400, "unsafe_database",
                                       "Этот файл не является отдельной платёжной песочницей")
                marker = db.execute("SELECT marker FROM sb_meta").fetchall()
                if len(marker) != 1 or marker[0][0] != MARKER:
                    raise BillingError(400, "unsafe_database", "Неверный маркер тестовой базы")
                required = {"sb_meta", "sb_targets", "sb_orders", "sb_grants", "sb_events"}
                if tables != required:
                    raise BillingError(400, "unsafe_database",
                                       "В тестовой базе обнаружены посторонние или отсутствующие таблицы")
                return
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("INSERT INTO sb_meta(marker) VALUES (?)", (MARKER,))
            now = self._now()
            db.executemany(
                "INSERT INTO sb_targets(project,id,customer_id,title,valid_until) VALUES(?,?,?,?,?)",
                [
                    ("caucashub", "alice-load", "alice", "Демо-груз Алисы", now + 30 * DAY),
                    ("caucashub", "bob-load", "bob", "Демо-груз Бориса", now + 30 * DAY),
                    ("caucashub", "expired-load", "alice", "Демо-груз с истёкшим сроком", now - DAY),
                ],
            )

    @staticmethod
    def _customer(customer_id):
        if customer_id not in DEMO_CUSTOMERS:
            raise BillingError(401, "unknown_customer", "Выберите демонстрационный аккаунт")

    def catalog(self):
        return [p.public() for p in self._products.values()]

    def list_targets(self, customer_id):
        self._customer(customer_id)
        now = self._now()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM sb_targets WHERE project=? AND customer_id=? ORDER BY id",
                (self.project, customer_id),
            ).fetchall()
        return [{
            "id": r["id"], "title": r["title"], "valid_until": iso(r["valid_until"]),
            "eligible": r["valid_until"] > now,
        } for r in rows]

    def _target(self, db, customer_id, target_id):
        target = db.execute(
            "SELECT * FROM sb_targets WHERE project=? AND customer_id=? AND id=?",
            (self.project, customer_id, target_id),
        ).fetchone()
        if not target:
            raise BillingError(404, "target_not_found", "Демонстрационный груз не найден")
        return target

    def create_order(self, customer_id, product_code, idempotency_key, target_id=None):
        self._customer(customer_id)
        if not isinstance(idempotency_key, str) or not re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}", idempotency_key
        ):
            raise BillingError(400, "invalid_idempotency_key", "Нужен корректный ключ повтора")
        if not isinstance(product_code, str):
            raise BillingError(400, "invalid_product", "Нужен код продукта")
        if target_id is not None and not isinstance(target_id, str):
            raise BillingError(400, "invalid_target", "Нужен текстовый идентификатор груза")
        request_hash = hashlib.sha256(json.dumps(
            {"product_code": product_code, "target_id": target_id},
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        with self._transaction() as db:
            previous = db.execute(
                "SELECT * FROM sb_orders WHERE project=? AND customer_id=? AND idempotency_key=?",
                (self.project, customer_id, idempotency_key),
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise BillingError(409, "idempotency_conflict",
                                       "Этот ключ уже использован с другими условиями заказа")
                return self._order_dict(db, previous)
            product = self._products.get(product_code)
            if not product:
                raise BillingError(404, "product_not_found", "Для этого проекта продукт не настроен")
            if not product.enabled:
                raise BillingError(409, "product_unavailable", "Этот продукт ещё не готов к продаже")
            now = self._now()
            if product.kind == "boost":
                if not target_id:
                    raise BillingError(400, "target_required", "Выберите демонстрационный груз")
                target = self._target(db, customer_id, target_id)
                current_end = self._resource_end(db, customer_id, product.kind, target_id)
                if target["valid_until"] < max(now, current_end) + product.duration_seconds:
                    raise BillingError(409, "target_expiring",
                                       "Срок актуальности груза короче выбранного продвижения")
            elif target_id is not None:
                raise BillingError(400, "unexpected_target", "Подписка не привязана к грузу")
            order_id = str(uuid4())
            db.execute(
                """INSERT INTO sb_orders (
                    id,project,customer_id,product_code,product_title,kind,target_id,
                    amount_tetri,currency,duration_seconds,created_at,provider_tx_id,
                    idempotency_key,request_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (order_id, self.project, customer_id, product.code, product.title, product.kind,
                 target_id, product.price_tetri, product.currency, product.duration_seconds,
                 now, "sim_" + uuid4().hex, idempotency_key, request_hash),
            )
            return self._get_scoped(db, customer_id, order_id)

    def _get_scoped(self, db, customer_id, order_id):
        row = db.execute(
            "SELECT * FROM sb_orders WHERE project=? AND customer_id=? AND id=?",
            (self.project, customer_id, order_id),
        ).fetchone()
        if not row:
            raise BillingError(404, "order_not_found", "Заказ не найден")
        return self._order_dict(db, row)

    def get_order(self, customer_id, order_id):
        self._customer(customer_id)
        with closing(self._connect()) as db:
            return self._get_scoped(db, customer_id, order_id)

    def list_orders(self, customer_id):
        self._customer(customer_id)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM sb_orders WHERE project=? AND customer_id=? ORDER BY created_at,id",
                (self.project, customer_id),
            ).fetchall()
            return [self._order_dict(db, r) for r in rows]

    def _grant_dict(self, row):
        now = self._now()
        return {
            "id": row["id"], "order_id": row["order_id"], "project": row["project"],
            "customer_id": row["customer_id"], "kind": row["kind"], "target_id": row["target_id"],
            "starts_at": iso(row["starts_at"]), "ends_at": iso(row["ends_at"]),
            "revoked": row["revoked_at"] is not None, "revoked_at": iso(row["revoked_at"]),
            "active": row["revoked_at"] is None and row["starts_at"] <= now < row["ends_at"],
        }

    def _order_dict(self, db, row):
        names = ("id", "project", "customer_id", "product_code", "product_title", "kind",
                 "target_id", "amount_tetri", "currency", "status", "fulfillment_status",
                 "fulfillment_error", "provider_tx_id", "duration_seconds")
        result = {name: row[name] for name in names}
        result.update(created_at=iso(row["created_at"]), paid_at=iso(row["paid_at"]), sandbox=True)
        grant = db.execute("SELECT * FROM sb_grants WHERE order_id=?", (row["id"],)).fetchone()
        result["grant"] = self._grant_dict(grant) if grant else None
        return result

    def list_grants(self, customer_id):
        self._customer(customer_id)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM sb_grants WHERE project=? AND customer_id=? ORDER BY id",
                (self.project, customer_id),
            ).fetchall()
        return [self._grant_dict(r) for r in rows]

    def _resource_end(self, db, customer_id, kind, target_id):
        row = db.execute(
            """SELECT MAX(ends_at) FROM sb_grants
               WHERE project=? AND customer_id=? AND kind=? AND target_id IS ?
               AND revoked_at IS NULL""",
            (self.project, customer_id, kind, target_id),
        ).fetchone()
        return row[0] if row[0] is not None else 0.0

    def make_event(self, customer_id, order_id, outcome):
        # This is a trusted fake provider used by the LOCAL simulator only.
        # No endpoint exposes its signing key or accepts arbitrary event fields.
        order = self.get_order(customer_id, order_id)
        if outcome not in OUTCOMES:
            raise BillingError(400, "invalid_outcome", "Неизвестный результат тестовой оплаты")
        payload = {
            "event_id": str(uuid4()), "order_id": order["id"],
            "provider_tx_id": order["provider_tx_id"], "project": self.project,
            "amount_tetri": order["amount_tetri"], "currency": order["currency"],
            "outcome": outcome,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        return raw, signature

    def _verify(self, raw, signature):
        if not isinstance(raw, bytes) or len(raw) > 16_384 or not isinstance(signature, str):
            raise BillingError(400, "invalid_event", "Некорректное тестовое уведомление")
        expected = hmac.new(self._secret, raw, hashlib.sha256).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(expected, signature):
            raise BillingError(403, "invalid_signature", "Подпись тестового уведомления неверна")
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise BillingError(400, "invalid_event", "Некорректное тело уведомления")
        if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
            raise BillingError(400, "invalid_event", "Неожиданные поля уведомления")
        strings = ("event_id", "order_id", "provider_tx_id", "project", "currency", "outcome")
        if any(not isinstance(event[k], str) or not 1 <= len(event[k]) <= 128 for k in strings):
            raise BillingError(400, "invalid_event", "Некорректные поля уведомления")
        if type(event["amount_tetri"]) is not int or event["amount_tetri"] <= 0:
            raise BillingError(400, "invalid_event", "Сумма должна быть целым числом тетри")
        if event["project"] != self.project:
            raise BillingError(404, "order_not_found", "Заказ не найден")
        if event["outcome"] not in OUTCOMES:
            raise BillingError(400, "invalid_outcome", "Неизвестный статус уведомления")
        return event

    def accept_event(self, raw, signature):
        event = self._verify(raw, signature)  # Authenticate before opening a transaction.
        digest = hashlib.sha256(raw).hexdigest()
        with self._transaction() as db:
            order = db.execute(
                "SELECT * FROM sb_orders WHERE id=? AND project=?",
                (event["order_id"], self.project),
            ).fetchone()
            if not order:
                raise BillingError(404, "order_not_found", "Заказ не найден")
            if (event["provider_tx_id"] != order["provider_tx_id"]
                    or event["amount_tetri"] != order["amount_tetri"]
                    or event["currency"] != order["currency"]):
                raise BillingError(409, "payment_mismatch",
                                   "Платёж не соответствует заказу, сумме или валюте")
            existing = db.execute(
                "SELECT * FROM sb_events WHERE project=? AND event_id=?",
                (self.project, event["event_id"]),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise BillingError(409, "event_conflict",
                                       "Идентификатор уведомления повторён с другим содержимым")
                return self._order_dict(db, order)
            now = self._now()
            outcome = event["outcome"]
            status = order["status"]
            if outcome == status:
                # A second, valid event for the same settled outcome is a no-op.
                pass
            elif status == "pending" and outcome in {"failed", "cancelled", "expired"}:
                db.execute("UPDATE sb_orders SET status=? WHERE id=?", (outcome, order["id"]))
            elif status == "pending" and outcome == "paid":
                self._fulfill(db, order, now)
            elif status == "paid" and outcome == "refunded":
                self._refund(db, order, now)
            else:
                raise BillingError(409, "invalid_transition",
                                   "Для этого заказа такой переход уже невозможен")
            db.execute(
                "INSERT INTO sb_events(project,event_id,order_id,payload_hash,outcome,received_at)"
                " VALUES(?,?,?,?,?,?)",
                (self.project, event["event_id"], order["id"], digest, outcome, now),
            )
            return self._get_scoped(db, order["customer_id"], order["id"])

    def _fulfill(self, db, order, now):
        start = max(now, self._resource_end(
            db, order["customer_id"], order["kind"], order["target_id"]
        ))
        end = start + order["duration_seconds"]
        problem = None
        if order["kind"] == "boost":
            try:
                target = self._target(db, order["customer_id"], order["target_id"])
                if target["valid_until"] < end:
                    problem = "Груз больше не актуален на весь оплаченный срок"
            except BillingError:
                problem = "Груз больше не доступен для продвижения"
        # Valid money outcome is recorded even when fulfillment needs review.
        if problem:
            db.execute(
                """UPDATE sb_orders SET status='paid',paid_at=?,
                   fulfillment_status='needs_review',fulfillment_error=? WHERE id=?""",
                (now, problem, order["id"]),
            )
            return
        db.execute(
            """INSERT INTO sb_grants(order_id,project,customer_id,kind,target_id,starts_at,ends_at)
               VALUES(?,?,?,?,?,?,?)""",
            (order["id"], self.project, order["customer_id"], order["kind"],
             order["target_id"], start, end),
        )
        db.execute(
            """UPDATE sb_orders SET status='paid',paid_at=?,
               fulfillment_status='granted',fulfillment_error=NULL WHERE id=?""",
            (now, order["id"]),
        )

    def _refund(self, db, order, now):
        grant = db.execute(
            "SELECT * FROM sb_grants WHERE order_id=?", (order["id"],)
        ).fetchone()
        if grant:
            latest = db.execute(
                """SELECT MAX(id) FROM sb_grants WHERE project=? AND customer_id=?
                   AND kind=? AND target_id IS ? AND revoked_at IS NULL""",
                (self.project, order["customer_id"], order["kind"], order["target_id"]),
            ).fetchone()[0]
            if grant["id"] != latest:
                raise BillingError(409, "refund_latest_only",
                                   "В тесте сначала верните более позднее продление этой услуги")
            db.execute("UPDATE sb_grants SET revoked_at=? WHERE id=?", (now, grant["id"]))
        db.execute(
            """UPDATE sb_orders SET status='refunded',fulfillment_status='revoked',
               fulfillment_error=NULL WHERE id=?""", (order["id"],),
        )
