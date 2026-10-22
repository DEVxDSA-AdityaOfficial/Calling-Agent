"""Maps Retell call objects (from webhooks or polling) onto our Call rows."""

from datetime import datetime, timedelta, timezone

from .models import Call, utcnow

ACTIVE_STATUSES = {"queued", "ringing", "in_progress"}
TERMINAL_STATUSES = {"completed", "failed"}
GOAL_STATUSES = ["goal_achieved", "follow_up", "not_interested", "no_response", "failed"]

# disconnection_reason values that mean the conversation never really happened.
_FAILED_REASONS = {
    "dial_busy", "dial_failed", "dial_no_answer", "invalid_destination", "user_declined",
    "telephony_provider_permission_denied", "telephony_provider_unavailable", "sip_routing_error",
    "marked_as_spam", "network_blocked", "concurrency_limit_reached", "no_concurrency_fallback",
    "no_valid_payment", "credit_exhausted", "budget_reached", "scam_detected",
    "registered_call_timeout", "error_user_not_joined",
}
# Of those, the ones where the customer simply didn't pick up.
_NO_RESPONSE_REASONS = {"dial_busy", "dial_no_answer", "user_declined", "voicemail_reached", "registered_call_timeout"}

_REASON_OUTCOMES = {
    "voicemail_reached": "voicemail",
    "dial_no_answer": "no_answer",
    "dial_busy": "busy",
    "user_declined": "declined",
    "user_requested_dnc": "do_not_call",
    "user_requested_callback": "callback_requested",
}

_OUTCOME_GOAL = {
    "goal_achieved": "goal_achieved",
    "interested_follow_up": "follow_up",
    "callback_requested": "follow_up",
    "not_interested": "not_interested",
    "do_not_call": "not_interested",
    "wrong_person": "not_interested",
    "voicemail": "no_response",
    "no_answer": "no_response",
    "busy": "no_response",
    "declined": "no_response",
    "no_meaningful_conversation": "no_response",
}


def map_status(retell_status: str | None, disconnection_reason: str | None) -> str | None:
    if retell_status == "registered":
        return "ringing"
    if retell_status == "ongoing":
        return "in_progress"
    if retell_status in ("error", "not_connected"):
        return "failed"
    if retell_status == "ended":
        reason = disconnection_reason or ""
        if reason in _FAILED_REASONS or reason.startswith("error_"):
            return "failed"
        return "completed"
    return None


def goal_status_for(call: Call) -> str | None:
    """Business-level result of the call: what the dashboard reports as the call's outcome."""
    if call.status == "failed":
        return "no_response" if call.disconnection_reason in _NO_RESPONSE_REASONS else "failed"
    if call.status != "completed":
        return None
    if call.outcome in _OUTCOME_GOAL:
        return _OUTCOME_GOAL[call.outcome]
    if call.follow_up_requested:
        return "follow_up"
    return None  # analysis not in yet


def _ts(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None


def _turns(utterances: list[dict]) -> list[dict]:
    return [{"role": u.get("role"), "content": u.get("content")} for u in utterances if u.get("content")]


def apply_retell_call(call: Call, data: dict) -> None:
    """Merge a Retell call object into `call`. Safe to call repeatedly / out of order."""
    retell_status = data.get("call_status")
    reason = data.get("disconnection_reason")
    new_status = map_status(retell_status, reason)

    # Never move a finished call back to an active state (webhooks can arrive out of order).
    if new_status and not (call.status in TERMINAL_STATUSES and new_status in ACTIVE_STATUSES):
        call.status = new_status
        call.retell_status = retell_status
    if reason:
        call.disconnection_reason = reason

    call.started_at = _ts(data.get("start_timestamp")) or call.started_at
    call.ended_at = _ts(data.get("end_timestamp")) or call.ended_at
    if data.get("duration_ms") is not None:
        call.duration_ms = data["duration_ms"]
    elif call.duration_ms is None and call.started_at and call.ended_at:
        # Only as a fallback: a provider-reported duration (Retell/Twilio) is more accurate.
        call.duration_ms = int((_aware(call.ended_at) - _aware(call.started_at)).total_seconds() * 1000)

    if data.get("transcript"):
        call.transcript = data["transcript"]
    if data.get("transcript_object"):
        call.transcript_object = _turns(data["transcript_object"])
    if data.get("recording_url"):
        call.recording_url = data["recording_url"]

    analysis = data.get("call_analysis")
    if analysis:
        call.analysis_raw = analysis
        call.summary = analysis.get("call_summary") or call.summary
        call.sentiment = analysis.get("user_sentiment") or call.sentiment
        if analysis.get("call_successful") is not None:
            call.call_successful = analysis["call_successful"]
        custom = analysis.get("custom_analysis_data") or {}
        call.outcome = custom.get("call_outcome") or call.outcome
        call.customer_interest = custom.get("customer_interest") or call.customer_interest
        if custom.get("follow_up_requested") is not None:
            call.follow_up_requested = _as_bool(custom["follow_up_requested"])
        for key in ("appointment_preference", "primary_objection", "unanswered_questions", "next_action", "key_notes"):
            value = custom.get(key)
            if isinstance(value, str) and value.strip():
                setattr(call, key, value.strip())

    if call.status in TERMINAL_STATUSES and not call.outcome and reason in _REASON_OUTCOMES:
        call.outcome = _REASON_OUTCOMES[reason]
    if call.status == "failed" and not call.error and reason:
        call.error = reason.replace("_", " ")
    call.goal_status = goal_status_for(call) or call.goal_status

    call.last_synced_at = utcnow()


def set_live_transcript(call: Call, utterances: list[dict]) -> None:
    """Live transcript while the call is in progress (replaced by the final one when it ends)."""
    if call.status in ACTIVE_STATUSES and utterances:
        call.transcript_object = _turns(utterances)
        if call.status in ("queued", "ringing"):
            call.status = "in_progress"


def finish_direct_call(call: Call) -> None:
    """Twilio-pipeline calls are analysed by us; one that ended before anyone spoke has nothing to analyse."""
    if call.status == "completed" and not call.transcript_object and not call.outcome:
        call.outcome = "no_meaningful_conversation"
    apply_retell_call(call, {})


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def needs_refresh(call: Call, now: datetime | None = None) -> bool:
    """Whether polling Retell could still change this call (used when webhooks aren't reachable)."""
    if not call.retell_call_id:
        return False
    now = now or utcnow()
    last = _aware(call.last_synced_at)
    if last and now - last < timedelta(seconds=2):
        return False
    if call.status in ACTIVE_STATUSES:
        # Give up on calls that have been "active" for far longer than any call could last.
        return now - _aware(call.created_at) < timedelta(hours=3)
    # Post-call analysis lands a little after the call ends.
    if call.status == "completed" and call.analysis_raw is None:
        ended = _aware(call.ended_at) or _aware(call.updated_at)
        return ended is None or now - ended < timedelta(minutes=10)
    return False


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; Postgres keeps it.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
