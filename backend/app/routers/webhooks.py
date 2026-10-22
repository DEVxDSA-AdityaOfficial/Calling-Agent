import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..call_sync import apply_retell_call, set_live_transcript
from ..config import get_settings
from ..db import get_db
from ..models import Call, User
from ..providers import retell_settings
from ..retell_client import verify_webhook_signature

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

HANDLED_EVENTS = {"call_started", "call_ended", "call_analyzed", "transcript_updated"}


@router.post("/retell", status_code=204)
async def retell_webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    raw = (await request.body()).decode("utf-8")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid JSON")

    event, data = payload.get("event"), payload.get("call") or {}
    if event not in HANDLED_EVENTS or not data.get("call_id"):
        return Response(status_code=204)

    # Find the call first: the signature is made with the API key of the account that placed it.
    call = db.scalar(select(Call).where(Call.retell_call_id == data["call_id"]))
    if call is None:
        local_id = (data.get("metadata") or {}).get("local_call_id")
        call = db.get(Call, local_id) if isinstance(local_id, int) else None
    if call is None:
        log.info("Ignoring %s for unknown call %s", event, data["call_id"])
        return Response(status_code=204)

    api_key, _ = retell_settings(db, db.get(User, call.user_id))
    if settings.verify_webhook_signature and not verify_webhook_signature(
        raw, request.headers.get("x-retell-signature"), api_key
    ):
        raise HTTPException(401, "Invalid signature")

    if call.retell_call_id is None:
        call.retell_call_id = data["call_id"]
    if event == "transcript_updated":
        set_live_transcript(call, data.get("transcript_object") or [])
    else:
        apply_retell_call(call, data)
    db.commit()
    log.info("Webhook %s -> call %s is %s", event, call.id, call.status)
    return Response(status_code=204)
