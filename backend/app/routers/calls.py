import logging
import secrets

import phonenumbers
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..auth import current_user
from ..call_sync import ACTIVE_STATUSES, apply_retell_call, finish_direct_call, needs_refresh
from ..config import get_settings
from ..db import get_db
from ..models import Agent, Call, User, utcnow
from ..providers import credential_values, get_credential, retell_for_user, retell_settings
from ..speech.base import STTError
from ..speech.router import resolve_speech
from ..telephony.twilio import TwilioClient, TwilioError, stream_twiml
from ..retell_client import RetellClient, RetellError
from ..schemas import CallDetailOut, CallIn, CallOut, Stats

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calls", tags=["calls"])


def normalize_number(raw: str, region: str) -> str:
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        raise HTTPException(422, "That doesn't look like a phone number.")
    if not phonenumbers.is_valid_number(parsed):
        raise HTTPException(422, "That phone number isn't valid. Include the country code, e.g. +91 98765 43210.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _dynamic_variables(customer_name: str | None) -> dict[str, str]:
    if customer_name:
        return {"customer_name": customer_name, "greeting": f"Hi, is this {customer_name}?"}
    return {}  # fall back to the agent's default_dynamic_variables


def _out(call: Call, detail: bool = False):
    schema = CallDetailOut if detail else CallOut
    out = schema.model_validate(call)
    out.agent_name = call.agent.name if call.agent else None
    return out


def _optional_retell(db: Session, user: User) -> RetellClient | None:
    try:
        return retell_for_user(db, user)
    except RetellError:
        return None


def _mark_lost(call: Call) -> None:
    """Retell no longer knows this call (404): stop showing it as live forever."""
    if call.status in ACTIVE_STATUSES:
        call.status, call.goal_status = "failed", "failed"
        call.error = "Retell has no record of this call."
        call.last_synced_at = utcnow()


def _refresh(db: Session, call: Call, retell: RetellClient | None) -> None:
    if retell is None or not needs_refresh(call):
        return
    try:
        apply_retell_call(call, retell.get_call(call.retell_call_id))
        db.commit()
    except RetellError as exc:
        log.warning("Could not refresh call %s from Retell: %s", call.id, exc)
        db.rollback()
        if exc.status_code == 404:
            _mark_lost(call)
            db.commit()


def _get_call(db: Session, user: User, call_id: int) -> Call:
    call = db.get(Call, call_id, options=[joinedload(Call.agent)])
    if not call or call.user_id != user.id:
        raise HTTPException(404, "Call not found")
    return call


@router.post("", response_model=CallDetailOut, status_code=201)
def start_call(data: CallIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    if not data.consent_confirmed:
        raise HTTPException(422, "Confirm that the person you're calling has agreed to receive an AI call.")

    agent = db.get(Agent, data.agent_id)
    if not agent or agent.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    to_number = normalize_number(data.to_number, settings.default_phone_region)
    if settings.allowed_numbers and to_number not in settings.allowed_numbers:
        raise HTTPException(403, f"{to_number} is not in ALLOWED_DESTINATION_NUMBERS.")
    customer_name = (data.customer_name or "").strip() or None

    if agent.mode == "direct":
        return _start_direct_call(db, user, agent, to_number, customer_name)

    if agent.sync_status != "synced" or not agent.retell_agent_id:
        raise HTTPException(409, "This agent isn't synced with Retell yet. Open it and save it again.")

    retell = retell_for_user(db, user)
    _, from_number = retell_settings(db, user)
    if not from_number:
        raise HTTPException(409, "No caller number. Add one to Retell AI in Settings → API & Providers.")

    call = Call(
        user_id=user.id,
        agent_id=agent.id,
        to_number=to_number,
        from_number=from_number,
        customer_name=customer_name,
        mode=agent.mode,
        status="queued",
    )
    db.add(call)
    db.commit()

    try:
        result = retell.create_phone_call(
            {
                "from_number": from_number,
                "to_number": to_number,
                "override_agent_id": agent.retell_agent_id,
                # Use the agent's newest (draft) version so edits take effect without a publish step.
                "override_agent_version": "latest",
                "metadata": {"local_call_id": call.id, "local_agent_id": agent.id},
                "retell_llm_dynamic_variables": _dynamic_variables(customer_name),
            }
        )
    except RetellError as exc:
        call.status, call.error, call.goal_status = "failed", str(exc), "failed"
        db.commit()
        raise HTTPException(502, f"Couldn't start the call: {exc}")
    except Exception:
        log.exception("Unexpected error starting call %s", call.id)
        call.status, call.error, call.goal_status = "failed", "Unexpected error while starting the call.", "failed"
        db.commit()
        raise HTTPException(502, "Couldn't start the call because of an unexpected error.")

    call.retell_call_id = result.get("call_id")
    apply_retell_call(call, result)
    db.commit()
    db.refresh(call)
    return _out(call, detail=True)


def _start_direct_call(db: Session, user: User, agent: Agent, to_number: str, customer_name: str | None):
    """Twilio + Custom Brain: Twilio dials, then streams the call audio to /api/twilio/media/{token}."""
    from .agents import AgentNotReady, check_direct_ready

    try:
        check_direct_ready(db, user, agent)
        speech = resolve_speech(db, user, agent)  # chosen now and pinned for the whole call
    except (AgentNotReady, STTError) as exc:
        raise HTTPException(409, str(exc))
    twilio_values = credential_values(get_credential(db, user, "twilio"))
    settings = get_settings()
    token = secrets.token_urlsafe(24)
    call = Call(
        user_id=user.id,
        agent_id=agent.id,
        to_number=to_number,
        from_number=twilio_values["from_number"],
        customer_name=customer_name,
        mode="direct",
        status="queued",
        media_token=token,
        stt_provider=speech.provider.id,
        diagnostics={"stt": speech.describe(), "fallback_events": []},
    )
    db.add(call)
    db.commit()
    try:
        result = TwilioClient(twilio_values["account_sid"], twilio_values["auth_token"]).create_call(
            to=to_number,
            from_=twilio_values["from_number"],
            twiml=stream_twiml(f"{settings.websocket_base_url}/api/twilio/media/{token}", {"call_id": str(call.id)}),
            status_callback=f"{settings.public_base_url}/api/twilio/status/{token}",
        )
    except TwilioError as exc:
        call.status, call.error, call.goal_status = "failed", str(exc), "failed"
        db.commit()
        raise HTTPException(502, f"Couldn't start the call: {exc}")
    except Exception:
        # Never leave a call stuck in "queued" because of an unexpected failure.
        log.exception("Unexpected error starting direct call %s", call.id)
        call.status, call.error, call.goal_status = "failed", "Unexpected error while starting the call.", "failed"
        db.commit()
        raise HTTPException(502, "Couldn't start the call because of an unexpected error.")
    call.twilio_call_sid = result.get("sid")
    call.status = "ringing" if result.get("status") in ("queued", "ringing", "initiated") else call.status
    db.commit()
    db.refresh(call)
    return _out(call, detail=True)


@router.get("", response_model=list[CallOut])
def list_calls(
    agent_id: int | None = None,
    status: str | None = None,
    goal_status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = (
        select(Call)
        .options(joinedload(Call.agent))
        .where(Call.user_id == user.id)
        .order_by(Call.created_at.desc())
        .limit(limit)
    )
    if agent_id:
        query = query.where(Call.agent_id == agent_id)
    if status:
        query = query.where(Call.status == status)
    if goal_status:
        query = query.where(Call.goal_status == goal_status)
    calls = db.scalars(query).all()

    # Without public webhooks, keep active calls fresh by polling Retell (bounded to a few per request).
    stale = [c for c in calls if needs_refresh(c)][:5]
    if stale:
        retell = _optional_retell(db, user)
        for call in stale:
            _refresh(db, call, retell)
    return [_out(c) for c in calls]


@router.get("/stats", response_model=Stats)
def call_stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    def count(*where):
        return db.scalar(select(func.count(Call.id)).where(Call.user_id == user.id, *where)) or 0

    avg = db.scalar(
        select(func.avg(Call.duration_ms)).where(Call.user_id == user.id, Call.status == "completed")
    )
    return Stats(
        total_calls=count(),
        completed=count(Call.status == "completed"),
        failed=count(Call.status == "failed"),
        interested=count(
            or_(Call.customer_interest.in_(["high", "medium"]), Call.goal_status.in_(["goal_achieved", "follow_up"]))
        ),
        goal_achieved=count(Call.goal_status == "goal_achieved"),
        follow_ups=count(Call.follow_up_requested.is_(True)),
        avg_duration_ms=int(avg) if avg is not None else None,
    )


@router.post("/{call_id}/end", response_model=CallDetailOut)
def end_call(call_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    call = _get_call(db, user, call_id)
    if call.mode == "direct":
        if call.status not in ACTIVE_STATUSES or not call.twilio_call_sid:
            raise HTTPException(409, "This call isn't active.")
        values = credential_values(get_credential(db, user, "twilio"))
        try:
            TwilioClient(values.get("account_sid", ""), values.get("auth_token", "")).hangup(call.twilio_call_sid)
        except TwilioError as exc:
            if exc.status_code != 404:
                raise HTTPException(502, f"Couldn't end the call: {exc}")
        call.status, call.disconnection_reason = "completed", "manual_stopped"
        call.ended_at = call.ended_at or utcnow()
        finish_direct_call(call)
        db.commit()
        return _out(call, detail=True)
    if call.status not in ACTIVE_STATUSES or not call.retell_call_id:
        raise HTTPException(409, "This call isn't active.")
    retell = retell_for_user(db, user)
    try:
        retell.stop_call(call.retell_call_id)
    except RetellError as exc:
        if exc.status_code != 404:
            raise HTTPException(502, f"Couldn't end the call: {exc}")
        _mark_lost(call)
        db.commit()
        return _out(call, detail=True)
    # Pull the final state now; webhooks/polling fill in transcript and analysis later.
    try:
        apply_retell_call(call, retell.get_call(call.retell_call_id))
    except RetellError:
        pass
    db.commit()
    return _out(call, detail=True)


@router.get("/{call_id}", response_model=CallDetailOut)
def get_call(call_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    call = _get_call(db, user, call_id)
    if needs_refresh(call):
        _refresh(db, call, _optional_retell(db, user))
    return _out(call, detail=True)
