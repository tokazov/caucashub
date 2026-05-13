# AUDIT — Task 3: Account Deletion & Anonymization

**File audited:** `app/routers/users.py`  
**Date:** 2026-05-12  
**Auditor:** Subagent (Sprint Stage 3, P1)

---

## 1. Full Deletion Function Code

```python
@router.delete("/me")
async def delete_account(
    data: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user_obj),
):
    """
    ADR-010 GDPR: Soft delete аккаунта.
    Требует подтверждения словом 'УДАЛИТЬ'.
    Блокируется при наличии активных сделок.
    """
    from app.models.deal import Deal, DealStatus
    from app.models.load import Load, LoadStatus
    from app.models.response import Response, ResponseStatus
    from app.services.audit_log import log_status_change

    # 1. Проверка подтверждения (case-sensitive)
    if data.confirmation != "УДАЛИТЬ":
        raise HTTPException(
            status_code=400,
            detail="Для подтверждения введите слово УДАЛИТЬ (точно, с учётом регистра)"
        )

    user_id = current_user.id

    # 2. Проверяем активные сделки
    BLOCKING_STATUSES = [
        DealStatus.confirmed, DealStatus.loading,
        DealStatus.in_transit, DealStatus.delivered, DealStatus.disputed,
    ]
    active_deals_res = await db.execute(
        select(Deal).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id),
            Deal.status.in_(BLOCKING_STATUSES)
        )
    )
    active_deals = active_deals_res.scalars().all()
    if active_deals:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Нельзя удалить аккаунт с активными сделками...",
                "active_deal_ids": [d.id for d in active_deals],
            }
        )

    old_email = current_user.email
    now = datetime.now(timezone.utc)

    # 3a. Отменяем все активные грузы
    loads_res = await db.execute(
        select(Load).where(Load.user_id == user_id, Load.status == LoadStatus.active)
    )
    canceled_count = 0
    for load in loads_res.scalars().all():
        load.status = LoadStatus.canceled
        canceled_count += 1

    # 3b. Отзываем все pending-отклики
    resp_res = await db.execute(
        select(Response).where(
            Response.user_id == user_id,
            Response.status == ResponseStatus.pending,
        )
    )
    withdrawn_count = 0
    for resp in resp_res.scalars().all():
        resp.status = ResponseStatus.withdrawn
        withdrawn_count += 1

    # 3c. Анонимизируем пользователя
    current_user.email         = f"deleted_{user_id}@caucashub.deleted"
    current_user.phone         = None
    current_user.company_name  = f"Удалённый пользователь #{user_id}"
    current_user.full_name     = None
    current_user.telegram_id   = None
    current_user.hashed_password = "<deleted>"
    current_user.password_changed_at = now
    current_user.is_active     = False
    current_user.is_deleted    = True
    current_user.deleted_at    = now

    # 3d. Audit log
    await log_status_change(...)

    await db.commit()
    invalidate_counters_cache()

    if old_email:
        asyncio.create_task(_send_deletion_email(old_email, user_id, now))

    return {
        "deleted": True,
        "loads_canceled": canceled_count,
        "responses_withdrawn": withdrawn_count,
    }
```

---

## 2. User Fields Changed on Delete

| Field | Before | After |
|---|---|---|
| `email` | real email | `deleted_{id}@caucashub.deleted` (placeholder) |
| `phone` | phone number | `None` |
| `company_name` | real name | `"Удалённый пользователь #{id}"` |
| `full_name` | real name | `None` |
| `telegram_id` | Telegram ID | `None` |
| `hashed_password` | bcrypt hash | `"<deleted>"` |
| `password_changed_at` | last change | current UTC time (→ invalidates JWT) |
| `is_active` | `True` | `False` |
| `is_deleted` | `False` | `True` |
| `deleted_at` | `None` | current UTC datetime |
| `inn` | ИНН | **NOT changed** (налоговое хранение 6 лет) |

---

## 3. What Happens to Loads, Responses, Deals, Subscriptions

### Loads
- All loads with `status = active` → set to `LoadStatus.canceled`
- Loads in other statuses (completed, canceled, draft) → **NOT touched**
- Load records remain in DB (soft delete paradigm — historical data preserved)

### Responses
- All responses with `status = pending` → set to `ResponseStatus.withdrawn`
- Responses in other statuses (accepted, rejected, withdrawn) → **NOT touched**
- Response records remain in DB

### Deals
- **Blocking:** If any deal has status in `[confirmed, loading, in_transit, delivered, disputed]` → deletion is **blocked** with HTTP 400
- Deals in `canceled` or `completed` status → NOT blocked, remain in DB unchanged
- After deletion, deals reference `shipper_id`/`carrier_id` that now points to anonymized user record

### Subscriptions
- **⚠️ NOT HANDLED** — no subscription cancellation logic found in `delete_account`
- If a user has active subscriptions (e.g., Pro plan), they are NOT canceled or refunded
- `plan` field on User is NOT reset to `free`
- **Risk:** orphaned subscription data if billing module is added later

---

## 4. JWT Revocation Check

**Mechanism:** Timestamp-based invalidation (not token blacklist)

```python
current_user.password_changed_at = now  # ← set to deletion timestamp
```

In `app/routers/auth.py` → `require_user_obj`, the JWT validation checks:
- The JWT's `iat` (issued-at) against `user.password_changed_at`
- If `iat < password_changed_at` → token is rejected as stale

Additionally:
- `is_active = False` and `is_deleted = True` → `require_user_obj` returns HTTP 401 for any subsequent request

**Verdict:** JWT revocation is **effectively implemented** via:
1. `password_changed_at` timestamp bump invalidates all pre-deletion tokens
2. `is_deleted = True` check blocks even freshly issued tokens (if any slip through)

**Gap:** Tokens issued in the milliseconds between `password_changed_at` being set and `db.commit()` could theoretically pass if `iat == password_changed_at` (edge case, acceptable risk).

---

## 5. Rate Limiting on DELETE `/me`

**Finding: NO rate limiting on DELETE `/me`.**

- No `slowapi` / `fastapi-limiter` decorators found on `delete_account`
- No IP-based or user-based rate limit applied
- The endpoint requires `confirmation = "УДАЛИТЬ"` which provides some brute-force resistance, but a scripted attacker could still spam it

**Risk Level: Medium**
- Practical risk is low because: (a) authentication required, (b) string confirmation required
- However, combined with a compromised session, unlimited deletion attempts could be used in automation scripts

**Recommendation:** Add rate limit of 3 attempts per hour per user_id.

---

## 6. Password Confirmation Requirement

**Current implementation:**

```python
class DeleteAccountRequest(BaseModel):
    confirmation: str  # должно быть "УДАЛИТЬ"

if data.confirmation != "УДАЛИТЬ":
    raise HTTPException(status_code=400, detail="...")
```

**Type:** Text phrase confirmation (`"УДАЛИТЬ"`), NOT password re-entry.

**Pros:**
- Simple UX
- Prevents accidental deletion
- Case-sensitive check (exact match)

**Cons:**
- Does **not** verify identity — if session token is stolen, attacker can delete account without knowing the password
- Unlike password re-entry, this provides no additional authentication factor

**Verdict:** Confirmation word is present and case-sensitive. **Password re-entry is NOT required.**  
**Recommendation (ADR-010 improvement):** Add `current_password: str` field and verify via `verify_password(data.current_password, current_user.hashed_password)` for stronger identity verification before irreversible deletion.

---

## Summary

| Check | Status | Notes |
|---|---|---|
| Deletion function exists | ✅ | `DELETE /me` |
| User fields anonymized | ✅ | 9 fields wiped |
| ИНН preserved | ✅ | Tax compliance |
| Active loads canceled | ✅ | `active → canceled` |
| Pending responses withdrawn | ✅ | `pending → withdrawn` |
| Active deals blocked | ✅ | 5 blocking statuses |
| Subscriptions handled | ❌ | Not canceled/reset |
| JWT revocation | ✅ | Via `password_changed_at` |
| Rate limiting on DELETE | ❌ | Not present |
| Password confirmation | ⚠️ | Text phrase only, no password |
| Audit log | ✅ | `log_status_change` called |
| Email notification | ✅ | Async, non-blocking |
| Stats cache invalidation | ✅ | `invalidate_counters_cache()` |
