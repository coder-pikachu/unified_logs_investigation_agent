"""Investigate chat: human-initiated RCA over the same agent pipeline.

A user describes an issue (optionally with a screenshot). A vision LLM triages
it into signals (journeys, error codes, ids, timeframe), a deterministic ladder
finds matching audit evidence, and the existing RCA graph investigates. Chat
history lives in Atlas (`chat_sessions`) — the one-platform story extends to
the support conversation itself.

POST /api/chat              one turn  (text + optional image data URL)
GET  /api/chat/{session_id} session history
GET  /api/chat/image/{id}   stored screenshot bytes
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Response
from pydantic import BaseModel, Field

from .. import llm
from ..config import settings
from ..db import get_db, jsonable
from ..graph.nodes import _COST_IN, _COST_OUT
from ..graph.prompts import GLOSSARY
from ..graph.runner import run_incident
from .routes import _ERR_PATHS, _search
from .sse import bus

router = APIRouter(prefix="/api")

MAX_IMAGE_B64 = 4 * 1024 * 1024  # 4 MB of base64 payload

# The 17 real journeys the platform monitors (cmnd_id — human meaning).
JOURNEY_CATALOG: list[tuple[str, str]] = [
    ("auth_login_user_authenticate", "user login / authentication (IAM via EIS)"),
    ("upi_payment_send_money", "UPI send-money payments (UPI switch via UNIPAY)"),
    ("martech_hyper-personalization_offers_fetch", "personalized offers on the dashboard (Martech via EIS)"),
    ("pfm_financial-fitness_customer_kyc_fetch", "PFM financial-fitness KYC (THINK360 via EIS)"),
    ("pfm_financial-fitness_consent_fetch", "PFM financial-fitness consent"),
    ("pfm_financial-fitness_summary_fetch", "PFM financial-fitness summary (THINK360 via EIS)"),
    ("lending_demand_demand-loan-closure_manage", "demand-loan closure (CBS via EIS)"),
    ("loan_personal_papl_getEligibleLoanDetails", "pre-approved personal-loan eligibility"),
    ("gi_gsa_purchase_validate_checks", "general-insurance GSA purchase validation (web channel)"),
    ("home_dashboard_notification_getAllNotifications", "home-dashboard notifications"),
    ("home_dashboard_cards_getAllCCAccountSummary", "credit-card summary on the dashboard"),
    ("home_user_preferred_lang_set", "preferred-language setting"),
    ("feedback_customer_txn-counter-and-rules_fetch", "feedback / txn-counter rules"),
    ("billpay_autopay_pendingbills_fetch", "billpay autopay pending bills (UNIPAY BBPS)"),
    ("billpay_autopay_favouritebillers_query", "billpay favourite billers (UNIPAY BBPS)"),
    ("ops_martech_audience_refresh_execute", "ops job: Martech audience refresh"),
    ("ops_eis_config_deploy_execute", "ops job: EIS config deploy"),
]

TRIAGE_SYSTEM = (
    "You triage customer-issue reports for the NOVA banking super-app so an RCA agent "
    "can search the audit logs.\n"
    f"{GLOSSARY}\n"
    "JOURNEY CATALOG (cmnd_id — meaning):\n"
    + "\n".join(f"- {c} — {d}" for c, d in JOURNEY_CATALOG)
    + "\n\nRules:\n"
    "- Map colloquial issue language ('offers missing', 'bill payment failing', 'login broken') to the "
    "CLOSEST catalog cmnd_ids; use [] when nothing plausibly matches (never invent journeys).\n"
    "- errCds: only codes actually visible in the text/screenshot (e.g. TEEIS009, BS000001, BSYHP003, 5151).\n"
    "- intent is 'follow_up' ONLY when the user is asking about the incident already under discussion "
    "(e.g. 'what should we do?', 'who was affected?'); a new symptom report is 'new_issue'.\n"
    "- Ids (trnsId/sessnTknId/usrId/usrRltnshpNo): only when explicitly present; else empty string."
)

FOLLOWUP_SYSTEM = (
    "You are the NOVA RCA assistant. Answer the user's follow-up question using ONLY the incident "
    "JSON below. Be concrete: cite origin, fault class, error codes, affected journeys/users, and "
    "recommendations. If the incident does not answer it, say so honestly.\n\nINCIDENT:\n"
)


class Triage(BaseModel):
    intent: str = Field(description="'new_issue' or 'follow_up' on the incident already discussed")
    journeys: list[str] = Field(description="matching cmnd_id values from the catalog, [] if none")
    errCds: list[str] = Field(description="error codes visible in the description/screenshot")
    trnsId: str = Field(description="explicit trns_id if present, else ''")
    sessnTknId: str = Field(description="explicit sessn_tkn_id if present, else ''")
    usrId: str = Field(description="explicit usr_id if present, else ''")
    usrRltnshpNo: str = Field(description="explicit relationship number if present, else ''")
    timeframeMinutes: int = Field(description="lookback window in minutes; 0 = default")
    screenSummary: str = Field(description="one sentence: what the screenshot/description shows")


class ChatTurn(BaseModel):
    sessionId: str | None = None
    message: str
    image: str | None = None  # full data URL "data:image/png;base64,..."


# ------------------------------------------------------------------ helpers

def _split_data_url(image: str) -> tuple[str, str]:
    """data URL -> (contentType, base64). Raises ValueError when malformed."""
    if "," not in image:
        raise ValueError("malformed data URL")
    header, b64 = image.split(",", 1)
    content_type = "image/png"
    if header.startswith("data:"):
        ct = header[5:].split(";", 1)[0].strip()
        if ct:
            content_type = ct
    if not b64.strip():
        raise ValueError("empty image payload")
    return content_type, b64


def _no_match_reply(minutes: int) -> str:
    families = ", ".join(sorted({c.split("_")[0] for c, _ in JOURNEY_CATALOG}))
    catalog = "; ".join(d for _, d in JOURNEY_CATALOG[:8])
    return (
        f"I searched the last {minutes} minutes of audit_transaction / audit_error / audit_service "
        f"and found no matching failures. I monitor these journey families: {families} — e.g. {catalog}. "
        f"Fire a scenario (`make sim`) or widen the timeframe and ask again."
    )


def _msg(role: str, text: str, image_id: str | None = None, incident_key: str | None = None) -> dict:
    return {"role": role, "text": text, "ts": dt.datetime.now(dt.timezone.utc),
            "imageId": image_id, "incidentKey": incident_key}


def _append(session_id: str, message: dict, incident_key: str | None = None) -> None:
    update: dict = {"$push": {"messages": message},
                    "$set": {"updatedAt": dt.datetime.now(dt.timezone.utc)},
                    "$setOnInsert": {"createdAt": dt.datetime.now(dt.timezone.utc)}}
    if incident_key:
        update["$set"]["lastIncidentKey"] = incident_key
    get_db()[settings.C_CHAT].update_one({"_id": session_id}, update, upsert=True)


def _publish_tokens(usage: dict) -> None:
    cost = round(usage.get("prompt", 0) * _COST_IN + usage.get("completion", 0) * _COST_OUT, 6)
    bus.publish({"type": "token", "payload": {"tokens": usage.get("total", 0), "cost": cost}})


def find_candidates(triage: Triage, message: str) -> tuple[list[str], list[str]]:
    """Deterministic evidence ladder -> (trns_ids, sessn_tkn_ids), capped 20/20."""
    db = get_db()
    minutes = triage.timeframeMinutes or settings.chat_lookback_minutes
    w = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    trns: list[str] = []
    sessions: list[str] = []

    def take(docs) -> None:
        for d in docs:
            t = d.get("trns_id")
            s = d.get("sessn_tkn_id")
            if t and t not in trns:
                trns.append(t)
            if s and s not in sessions:
                sessions.append(s)

    # a. explicit ids
    if triage.trnsId:
        trns.append(triage.trnsId)
    for field, val in (("sessn_tkn_id", triage.sessnTknId), ("usr_id", triage.usrId),
                       ("usr_rltnshp_no", triage.usrRltnshpNo)):
        if not val:
            continue
        # TXN only: every journey action writes audit_transaction, so the same
        # trns_ids surface here (indexed), and collect() joins ERR/SVC on trns_id.
        take(db[settings.C_TXN].find({field: val, "strt_time": {"$gte": w}}).limit(50))

    # b. error codes
    if triage.errCds:
        codes = [c for c in triage.errCds if c]
        take(db[settings.C_ERR].find(
            {"$or": [{"err_cd": {"$in": codes}}, {"biz_err_cd_1": {"$in": codes}}],
             "err_time": {"$gte": w}}).limit(50))
        take(db[settings.C_SVC].find({"err_cd": {"$in": codes}, "crtd_on": {"$gte": w}}).limit(50))

    # c. journeys with errored transactions
    if triage.journeys:
        take(db[settings.C_TXN].find(
            {"cmnd_id": {"$in": triage.journeys}, "trns_stts": "error",
             "strt_time": {"$gte": w}}).limit(50))

    # d. Atlas Search fallback over the error text — ONLY when triage produced no
    # structured signal at all. If it named journeys/codes and they yielded no
    # evidence, the honest answer is "no matching failures", not a fuzzy match
    # onto unrelated errors.
    no_signal = not (triage.journeys or triage.errCds or triage.trnsId
                     or triage.sessnTknId or triage.usrId or triage.usrRltnshpNo)
    if not trns and no_signal and message.strip():
        hits = _search(settings.C_ERR, settings.IDX_ERR_SEARCH, message.strip(), _ERR_PATHS)
        take(h for h in hits if "__error__" not in h)

    return trns[:20], sessions[:20]


def _investigate(session_id: str, trigger: dict) -> None:
    """Background: run the graph, then summarize into the chat + SSE."""
    key = trigger["incident_key"]
    try:
        run_incident(trigger)
        doc = get_db()[settings.C_INCIDENTS].find_one({"incidentKey": key}) or {}
        rca = doc.get("rca") or {}
        recs = doc.get("recommendations") or []
        top = recs[0]["action"] if recs else "see the incident recommendations"
        text = (f"RCA complete — **{doc.get('faultClass', 'mixed')}** fault. "
                f"Origin: `{doc.get('originComponent', '?')}`. "
                f"{rca.get('rootCause', 'See the incident detail.')} "
                f"(confidence {rca.get('confidence', '?')}). Top action: {top}. "
                f"Open the incident for the cited evidence.")
    except Exception as e:  # never leave the chat hanging silently
        text = f"The investigation failed: {str(e)[:200]}"
    message = _msg("assistant", text, incident_key=key)
    _append(session_id, message, incident_key=key)
    bus.publish({"type": "chat", "sessionId": session_id, "incidentKey": key,
                 "payload": {"message": jsonable(message)}})


# ------------------------------------------------------------------ endpoints

@router.post("/chat")
def chat(body: ChatTurn = Body(...)) -> dict:
    db = get_db()
    session_id = body.sessionId or str(uuid4())

    image_id: str | None = None
    if body.image:
        if len(body.image) > MAX_IMAGE_B64:
            raise HTTPException(400, "image too large (4MB max)")
        try:
            content_type, b64 = _split_data_url(body.image)
        except ValueError as e:
            raise HTTPException(400, str(e))
        image_id = str(uuid4())
        db[settings.C_CHAT_IMG].insert_one({"_id": image_id, "sessionId": session_id,
                                            "data": b64, "contentType": content_type,
                                            "ts": dt.datetime.now(dt.timezone.utc)})

    _append(session_id, _msg("user", body.message, image_id=image_id))

    # ---- triage (vision when a screenshot is attached; degrade to text-only)
    vision_note = ""
    try:
        triage, usage = llm.structured(
            Triage, TRIAGE_SYSTEM, body.message,
            role="vision" if body.image else "fast", image_url=body.image)
    except Exception:
        vision_note = "⚠ screenshot could not be analyzed — triaging from the text only. "
        triage, usage = llm.structured(Triage, TRIAGE_SYSTEM, body.message, role="fast")
    _publish_tokens(usage)

    session = db[settings.C_CHAT].find_one({"_id": session_id}) or {}
    last_key = session.get("lastIncidentKey")

    # ---- follow-up over the already-linked incident
    if triage.intent == "follow_up" and last_key:
        inc = db[settings.C_INCIDENTS].find_one({"incidentKey": last_key}) or {}
        for heavy in ("timeline", "verifications", "recallArms", "nodeTrace"):
            inc.pop(heavy, None)
        history = [{"role": m["role"], "content": m.get("text", "")}
                   for m in (session.get("messages") or [])[-10:]]
        answer, usage = llm.converse(FOLLOWUP_SYSTEM + json.dumps(jsonable(inc), default=str)[:12000],
                                     history + [{"role": "user", "content": body.message}])
        _publish_tokens(usage)
        reply = _msg("assistant", vision_note + answer, incident_key=last_key)
        _append(session_id, reply)
        return {"sessionId": session_id, "reply": jsonable(reply), "incidentKey": last_key}

    # ---- evidence search
    minutes = triage.timeframeMinutes or settings.chat_lookback_minutes
    trns, sessions = find_candidates(triage, body.message)

    if not trns:
        reply = _msg("assistant", vision_note + _no_match_reply(minutes))
        _append(session_id, reply)
        return {"sessionId": session_id, "reply": jsonable(reply), "incidentKey": None}

    # ---- an existing recent incident already covers this evidence
    now = dt.datetime.now(dt.timezone.utc)
    recent = db[settings.C_INCIDENTS].find_one(
        {"trnsIds": {"$in": trns}, "createdAt": {"$gte": now - dt.timedelta(minutes=30)}})
    if recent:
        rca = recent.get("rca") or {}
        text = (f"{vision_note}This matches incident `{recent['incidentKey']}` "
                f"(**{recent.get('faultClass', 'mixed')}** fault) — "
                f"{rca.get('rootCause', 'analysis in progress')} "
                f"Open the incident for the full timeline and evidence.")
        reply = _msg("assistant", text, incident_key=recent["incidentKey"])
        _append(session_id, reply, incident_key=recent["incidentKey"])
        return {"sessionId": session_id, "reply": jsonable(reply),
                "incidentKey": recent["incidentKey"]}

    # ---- launch a new investigation (idempotent claim, same as the watcher)
    incident_key = f"chat-{session_id[:8]}:{now:%Y-%m-%dT%H:%M}"
    db[settings.C_INCIDENTS].update_one(
        {"incidentKey": incident_key},
        {"$setOnInsert": {"incidentKey": incident_key, "status": "queued", "createdAt": now,
                          "signature": "chat", "trnsIds": trns, "sessnTknIds": sessions}},
        upsert=True,
    )
    trigger = {"incident_key": incident_key, "trns_ids": trns, "sessn_tkn_ids": sessions,
               "signature": "chat", "source": "chat", "sessionId": session_id}
    threading.Thread(target=_investigate, args=(session_id, trigger), daemon=True).start()

    codes = ", ".join(triage.errCds[:4]) if triage.errCds else "no explicit codes"
    text = (f"{vision_note}Found {len(trns)} failing transaction(s) across {max(len(sessions), 1)} "
            f"session(s) in the last {minutes} min ({codes}). Investigating — watch AGENT WORKFLOW; "
            f"I'll reply here when the RCA lands.")
    reply = _msg("assistant", text, incident_key=incident_key)
    _append(session_id, reply, incident_key=incident_key)
    return {"sessionId": session_id, "reply": jsonable(reply), "incidentKey": incident_key}


@router.get("/chat/image/{image_id}")
def chat_image(image_id: str) -> Response:
    doc = get_db()[settings.C_CHAT_IMG].find_one({"_id": image_id})
    if not doc:
        raise HTTPException(404, "image not found")
    return Response(content=base64.b64decode(doc["data"]), media_type=doc.get("contentType", "image/png"))


@router.get("/chat/{session_id}")
def chat_session(session_id: str) -> dict:
    doc = get_db()[settings.C_CHAT].find_one({"_id": session_id})
    return jsonable(doc) if doc else {}
