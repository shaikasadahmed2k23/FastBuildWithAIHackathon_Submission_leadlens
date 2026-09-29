"""Human approval queue. Nothing changes CRM data until a person approves it.

Lifecycle: pending -> approved -> executed, or pending -> rejected.
Every transition is written to ``audit_log``.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field

from app import db
from app.cleaning import refresh_issues
from app.config import AS_OF, ALL_STAGES
from app.scoring import rescore

ActionType = Literal["outreach", "merge", "stage_change"]
ActionStatus = Literal["pending", "approved", "rejected", "executed"]


class ActionError(ValueError):
    """Invalid request (bad payload, unknown leads)."""


class ActionConflict(RuntimeError):
    """The action is not in a state that allows the requested transition."""


class AuditEntry(BaseModel):
    id: int
    action_id: str
    event: str
    at: datetime
    actor: str


class Action(BaseModel):
    action_id: str
    type: ActionType
    lead_ids: list[str]
    payload: dict[str, Any]
    status: ActionStatus
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    note: str | None = None
    audit: list[AuditEntry] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _audit(cur: duckdb.DuckDBPyConnection, action_id: str, event: str, actor: str) -> None:
    next_id = cur.execute("SELECT coalesce(max(id), 0) + 1 FROM audit_log").fetchone()[0]
    cur.execute('INSERT INTO audit_log (id, action_id, event, "at", actor) VALUES (?, ?, ?, ?, ?)',
                [next_id, action_id, event, _now(), actor])


def _row_to_action(row: dict[str, Any], audit: list[AuditEntry] | None = None) -> Action:
    return Action(
        action_id=row["action_id"], type=row["type"], lead_ids=list(row["lead_ids"]),
        payload=json.loads(row["payload_json"]), status=row["status"], created_at=row["created_at"],
        decided_at=row["decided_at"], decided_by=row["decided_by"], note=row["note"], audit=audit or [],
    )


def validate_payload(type_: ActionType, lead_ids: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    if not lead_ids:
        raise ActionError("at least one lead_id is required")
    if len(set(lead_ids)) != len(lead_ids):
        raise ActionError("lead_ids must be unique")
    if type_ == "stage_change":
        if payload.get("stage") not in ALL_STAGES:
            raise ActionError(f"payload.stage must be one of {list(ALL_STAGES)}")
        return {"stage": payload["stage"]}
    if type_ == "merge":
        if len(lead_ids) < 2:
            raise ActionError("merge needs at least two lead_ids")
        primary = payload.get("primary_id", lead_ids[0])
        if primary not in lead_ids:
            raise ActionError("payload.primary_id must be one of lead_ids")
        return {"primary_id": primary}
    subject, body = str(payload.get("subject", "")).strip(), str(payload.get("body", "")).strip()
    if not subject or not body:
        raise ActionError("outreach needs payload.subject and payload.body")
    return {"subject": subject, "body": body, "channel": payload.get("channel", "email"),
            "citations": payload.get("citations", [])}


def create(type_: ActionType, lead_ids: list[str], payload: dict[str, Any], actor: str, note: str | None = None) -> Action:
    clean = validate_payload(type_, lead_ids, payload)
    with db.write_cursor() as cur:
        found = {r[0] for r in cur.execute("SELECT lead_id FROM leads WHERE lead_id IN (SELECT unnest(?))",
                                           [lead_ids]).fetchall()}
        missing = [lid for lid in lead_ids if lid not in found]
        if missing:
            raise ActionError(f"unknown lead_ids: {', '.join(missing)}")
        next_n = cur.execute(
            "SELECT coalesce(max(CAST(substr(action_id, 4) AS INTEGER)), 0) + 1 FROM actions").fetchone()[0]
        action_id = f"AX-{next_n:05d}"
        cur.execute(
            "INSERT INTO actions (action_id, type, lead_ids, payload_json, status, created_at, note) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            [action_id, type_, lead_ids, json.dumps(clean), _now(), note],
        )
        _audit(cur, action_id, f"created {type_} for {', '.join(lead_ids)}", actor)
    return get(action_id)


def get(action_id: str) -> Action:
    with db.cursor() as cur:
        rows = db.fetch_dicts(cur, "SELECT * FROM actions WHERE action_id = ?", [action_id])
        if not rows:
            raise KeyError(action_id)
        audit = [AuditEntry(**r) for r in db.fetch_dicts(
            cur, 'SELECT id, action_id, event, "at", actor FROM audit_log WHERE action_id = ? ORDER BY id', [action_id])]
    return _row_to_action(rows[0], audit)


def list_actions(status: ActionStatus | None = None, lead_id: str | None = None) -> list[Action]:
    conds, params = [], []
    if status:
        conds.append("status = ?")
        params.append(status)
    if lead_id:
        conds.append("list_contains(lead_ids, ?)")
        params.append(lead_id)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    with db.cursor() as cur:
        rows = db.fetch_dicts(cur, f"SELECT * FROM actions {where} ORDER BY created_at DESC, action_id DESC", params)
        audit: dict[str, list[AuditEntry]] = {}
        if rows:
            ids = [r["action_id"] for r in rows]
            for r in db.fetch_dicts(
                    cur, 'SELECT id, action_id, event, "at", actor FROM audit_log WHERE list_contains(?, action_id) ORDER BY id',
                    [ids]):
                audit.setdefault(r["action_id"], []).append(AuditEntry(**r))
    return [_row_to_action(r, audit.get(r["action_id"])) for r in rows]


def _decide(action_id: str, status: Literal["approved", "rejected"], actor: str, note: str | None) -> None:
    with db.write_cursor() as cur:
        row = cur.execute("SELECT status FROM actions WHERE action_id = ?", [action_id]).fetchone()
        if row is None:
            raise KeyError(action_id)
        if row[0] != "pending":
            raise ActionConflict(f"{action_id} is already {row[0]}")
        cur.execute("UPDATE actions SET status = ?, decided_at = ?, decided_by = ?, note = coalesce(?, note) "
                    "WHERE action_id = ?", [status, _now(), actor, note, action_id])
        _audit(cur, action_id, status + (f": {note}" if note else ""), actor)


def reject(action_id: str, actor: str, note: str | None = None) -> Action:
    _decide(action_id, "rejected", actor, note)
    return get(action_id)


def approve(action_id: str, actor: str, note: str | None = None) -> Action:
    """Approve, then execute. Execution failures leave the action 'approved' with an audit entry."""
    _decide(action_id, "approved", actor, note)
    action = get(action_id)
    with db.write_cursor() as cur:
        try:
            cur.execute("BEGIN TRANSACTION")
            summary, touched = _execute(cur, action)
            cur.execute("UPDATE actions SET status = 'executed' WHERE action_id = ?", [action_id])
            cur.execute("COMMIT")
        except (duckdb.Error, ActionError) as exc:
            cur.execute("ROLLBACK")
            _audit(cur, action_id, f"execution failed: {exc}", "system")
            return get(action_id)
        _audit(cur, action_id, f"executed: {summary}", "system")
        # Derived tables are recomputed after the commit; they can always be rebuilt.
        refresh_issues(cur, touched)
        rescore(cur, touched)
    return get(action_id)


def _execute(cur: duckdb.DuckDBPyConnection, action: Action) -> tuple[str, list[str]]:
    ids = action.lead_ids
    existing = {r[0] for r in cur.execute("SELECT lead_id FROM leads WHERE lead_id IN (SELECT unnest(?))",
                                          [ids]).fetchall()}
    gone = [lid for lid in ids if lid not in existing]
    if gone:
        raise ActionError(f"leads no longer exist: {', '.join(gone)}")

    if action.type == "stage_change":
        stage = action.payload["stage"]
        cur.execute("UPDATE leads SET stage = ?, updated_at = ? WHERE lead_id IN (SELECT unnest(?))", [stage, AS_OF, ids])
        return f"set stage to '{stage}' on {', '.join(ids)}", ids

    if action.type == "outreach":
        # Sending is simulated: record the touch so recency and staleness update.
        cur.execute(
            "UPDATE leads SET last_contacted_at = ?, updated_at = ?, "
            "stage = CASE WHEN stage = 'new' THEN 'contacted' ELSE stage END WHERE lead_id IN (SELECT unnest(?))",
            [AS_OF, AS_OF, ids],
        )
        return f"logged {action.payload.get('channel', 'email')} outreach to {', '.join(ids)}", ids

    primary = action.payload["primary_id"]
    others = [lid for lid in ids if lid != primary]
    filled = []
    for fld in ("email", "phone", "title"):
        n = cur.execute(
            f"""UPDATE leads SET {fld} = (
                    SELECT d.{fld} FROM leads d WHERE d.lead_id IN (SELECT unnest(?))
                      AND d.{fld} IS NOT NULL AND trim(d.{fld}) <> '' ORDER BY d.lead_id LIMIT 1)
                WHERE lead_id = ? AND ({fld} IS NULL OR trim({fld}) = '')
                  AND EXISTS (SELECT 1 FROM leads d WHERE d.lead_id IN (SELECT unnest(?))
                              AND d.{fld} IS NOT NULL AND trim(d.{fld}) <> '')
                RETURNING lead_id""",
            [others, primary, others],
        ).fetchall()
        if n:
            filled.append(fld)
    moved = cur.execute("UPDATE activities SET lead_id = ? WHERE lead_id IN (SELECT unnest(?)) RETURNING activity_id",
                        [primary, others]).fetchall()
    cur.execute("DELETE FROM data_issues WHERE lead_id IN (SELECT unnest(?)) OR related_lead_id IN (SELECT unnest(?))",
                [others, others])
    cur.execute("DELETE FROM lead_scores WHERE lead_id IN (SELECT unnest(?))", [others])
    cur.execute("DELETE FROM leads WHERE lead_id IN (SELECT unnest(?))", [others])
    cur.execute("UPDATE leads SET updated_at = ? WHERE lead_id = ?", [AS_OF, primary])
    extra = f", filled {', '.join(filled)}" if filled else ""
    return f"merged {', '.join(others)} into {primary} (moved {len(moved)} activities{extra})", [primary, *others]
