import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..conversation.base import ConversationModelError
from ..conversation.factory import get_conversation_model
from ..conversation.playbook import generate_playbook
from ..conversation.simulator import PERSONAS, evaluate, simulate_turn
from ..db import get_db
from ..models import Agent, Call, User
from ..prompt_builder import (
    DEFAULT_DYNAMIC_VARIABLES,
    AgentSpec,
    build_begin_message,
    build_post_call_analysis,
    build_prompt,
    retell_language,
)
from ..providers import retell_for_user
from ..retell_client import RetellClient, RetellError
from ..schemas import AgentIn, AgentOut, PromptPreview, SimEvaluateIn, SimTurnIn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

class AgentNotReady(Exception):
    pass


SPEC_FIELDS = (
    "name", "business_name", "script", "objective", "target_audience", "success_condition", "fallback_behavior",
    "max_duration_minutes", "additional_context", "dos_and_donts", "language", "tone", "opening_line", "mode",
)


def spec_for(data: AgentIn | Agent) -> AgentSpec:
    playbook = data.playbook
    if playbook is not None and not isinstance(playbook, dict):
        playbook = playbook.model_dump()
    return AgentSpec(**{f: getattr(data, f) for f in SPEC_FIELDS}, playbook=playbook)


def _get_agent(db: Session, user: User, agent_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent or agent.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    return agent


def llm_websocket_url(agent: Agent) -> str | None:
    base = get_settings().websocket_base_url
    # Retell appends /{call_id}. The token authenticates Retell's connection to this agent.
    return f"{base}/api/llm-ws/{agent.ws_token}" if base else None


def sync_to_retell(agent: Agent, retell: RetellClient) -> None:
    """Create or update the Retell response engine + voice agent that back this agent."""
    settings = get_settings()
    spec = spec_for(agent)

    if agent.mode == "custom_brain":
        ws_url = llm_websocket_url(agent)
        if not ws_url:
            raise RetellError(
                "Custom Brain needs PUBLIC_BASE_URL (a public https URL for this backend, e.g. an ngrok tunnel) "
                "so Retell can reach the conversation engine."
            )
        response_engine = {"type": "custom-llm", "llm_websocket_url": ws_url}
    else:
        llm_body = {
            "general_prompt": agent.generated_prompt,
            "begin_message": agent.begin_message,
            "start_speaker": "agent",
            "default_dynamic_variables": DEFAULT_DYNAMIC_VARIABLES,
            "general_tools": [
                {
                    "type": "end_call",
                    "name": "end_call",
                    "description": "Hang up after saying goodbye, once the conversation is complete, the customer "
                    "declines or asks not to be called, it's the wrong person, or after leaving a voicemail.",
                }
            ],
        }
        if agent.retell_llm_id:
            retell.update_llm(agent.retell_llm_id, llm_body)
        else:
            agent.retell_llm_id = retell.create_llm(llm_body)["llm_id"]
        response_engine = {"type": "retell-llm", "llm_id": agent.retell_llm_id}

    agent_body = {
        "agent_name": f"{agent.name} ({agent.business_name})",
        "response_engine": response_engine,
        "voice_id": agent.voice_id,
        "language": retell_language(agent.language),
        "post_call_analysis_data": build_post_call_analysis(spec),
        "max_call_duration_ms": max(agent.max_duration_minutes, 1) * 60_000 + 60_000,  # 1 min grace to wrap up
        "end_call_after_silence_ms": settings.end_call_after_silence_ms,
        "interruption_sensitivity": 0.8,
    }
    if settings.webhook_url:
        agent_body["webhook_url"] = settings.webhook_url
        agent_body["webhook_events"] = ["call_started", "call_ended", "call_analyzed", "transcript_updated"]
    if agent.retell_agent_id:
        retell.update_agent(agent.retell_agent_id, agent_body)
    else:
        agent.retell_agent_id = retell.create_agent(agent_body)["agent_id"]


def check_direct_ready(db: Session, user: User, agent: Agent) -> None:
    """Twilio + Custom Brain agents don't live on Retell; check everything a call will need instead."""
    from ..providers import credential_values, get_credential
    from ..speech.base import STTError
    from ..speech.router import resolve_speech

    if not get_settings().websocket_base_url:
        raise AgentNotReady("Twilio + Custom Brain needs PUBLIC_BASE_URL so Twilio can stream call audio to this backend.")
    twilio = credential_values(get_credential(db, user, "twilio"))
    if not (twilio.get("account_sid") and twilio.get("auth_token")):
        raise AgentNotReady("Connect Twilio in Settings → API & Providers.")
    if not twilio.get("from_number"):
        raise AgentNotReady("Add a Twilio caller number in Settings → API & Providers.")
    if not credential_values(get_credential(db, user, "elevenlabs")).get("api_key"):
        raise AgentNotReady("Connect ElevenLabs in Settings → API & Providers (it speaks the agent's replies).")
    try:
        resolve_speech(db, user, agent)
    except STTError as exc:
        raise AgentNotReady(str(exc)) from exc


def _save_and_sync(db: Session, agent: Agent, user: User) -> Agent:
    spec = spec_for(agent)
    agent.generated_prompt = build_prompt(spec)
    agent.begin_message = build_begin_message(spec)
    db.commit()  # persist the user's work even if a provider is unavailable
    if agent.mode == "direct":
        try:
            check_direct_ready(db, user, agent)
            agent.sync_status, agent.sync_error = "synced", None
        except AgentNotReady as exc:
            agent.sync_status, agent.sync_error = "error", str(exc)
        db.commit()
        db.refresh(agent)
        return agent
    try:
        sync_to_retell(agent, retell_for_user(db, user))
        agent.sync_status, agent.sync_error = "synced", None
    except RetellError as exc:
        log.warning("Retell sync failed for agent %s: %s", agent.id, exc)
        agent.sync_status, agent.sync_error = "error", str(exc)
    db.commit()
    db.refresh(agent)
    return agent


def _apply(agent: Agent, data: AgentIn) -> None:
    for key, value in data.model_dump(exclude={"playbook"}).items():
        setattr(agent, key, value)
    agent.playbook = data.playbook.model_dump() if data.playbook else None


@router.get("", response_model=list[AgentOut])
def list_agents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Agent).where(Agent.user_id == user.id).order_by(Agent.created_at.desc())).all()


@router.post("/preview", response_model=PromptPreview)
def preview_prompt(data: AgentIn, user: User = Depends(current_user)):
    spec = spec_for(data)
    return PromptPreview(prompt=build_prompt(spec), begin_message=build_begin_message(spec))


@router.post("/playbook")
async def create_playbook(data: AgentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Script-to-Agent intelligence: draft opening, questions, objection handling and success criteria."""
    try:
        model = get_conversation_model(db, user)
        return await generate_playbook(model, spec_for(data))
    except ConversationModelError as exc:
        raise HTTPException(502, str(exc))


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(data: AgentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = Agent(user_id=user.id, ws_token=secrets.token_urlsafe(24))
    _apply(agent, data)
    db.add(agent)
    return _save_and_sync(db, agent, user)


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _get_agent(db, user, agent_id)


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, data: AgentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = _get_agent(db, user, agent_id)
    _apply(agent, data)  # a mode change reuses the Retell agent and swaps its response engine
    return _save_and_sync(db, agent, user)


@router.post("/{agent_id}/sync", response_model=AgentOut)
def resync_agent(agent_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _save_and_sync(db, _get_agent(db, user, agent_id), user)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = _get_agent(db, user, agent_id)
    if db.scalar(select(Call.id).where(Call.agent_id == agent_id).limit(1)):
        raise HTTPException(409, "This agent has call history and can't be deleted.")
    db.delete(agent)
    db.commit()
    return Response(status_code=204)


# --- Pre-call simulator ---
def _check_persona(persona: str) -> None:
    if persona not in PERSONAS:
        raise HTTPException(422, f"Unknown persona; choose one of {', '.join(PERSONAS)}")


def _clean_history(history: list[dict]) -> list[dict]:
    return [
        {"role": "agent" if t.get("role") == "agent" else "user", "content": str(t.get("content", ""))[:2000]}
        for t in history
        if t.get("content")
    ]


@router.post("/{agent_id}/simulate/turn")
async def simulate(agent_id: int, data: SimTurnIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_persona(data.persona)
    agent = _get_agent(db, user, agent_id)
    try:
        model = get_conversation_model(db, user)
        return await simulate_turn(
            model, spec_for(agent), agent.generated_prompt, agent.begin_message, data.persona, _clean_history(data.history)
        )
    except ConversationModelError as exc:
        raise HTTPException(502, str(exc))


@router.post("/{agent_id}/simulate/evaluate")
async def simulate_evaluate(
    agent_id: int, data: SimEvaluateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    _check_persona(data.persona)
    agent = _get_agent(db, user, agent_id)
    try:
        model = get_conversation_model(db, user)
        return await evaluate(model, agent.generated_prompt, data.persona, _clean_history(data.history))
    except ConversationModelError as exc:
        raise HTTPException(502, str(exc))
