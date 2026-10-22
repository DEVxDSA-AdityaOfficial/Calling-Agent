from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..providers import (
    PROVIDERS,
    CredentialValidationError,
    credential_values,
    get_credential,
    replace_credential,
    test_connection,
)
from ..ratelimit import per_user
from ..schemas import ProviderFieldOut, ProviderIn, ProviderOut
from ..security import mask

router = APIRouter(prefix="/api/providers", tags=["providers"])


def provider_out(db: Session, user: User, provider_id: str) -> ProviderOut:
    definition = PROVIDERS[provider_id]
    cred = get_credential(db, user, provider_id)
    values = credential_values(cred)
    fields = [
        ProviderFieldOut(
            key=f.key,
            label=f.label,
            secret=f.secret,
            placeholder=f.placeholder,
            required=f.required,
            kind=f.kind,
            options=[{"value": v, "label": l} for v, l in f.options],
            help=f.help,
            # Secrets never leave the server: only a masked hint of the last 4 characters.
            value=mask(values.get(f.key)) if f.secret else values.get(f.key),
        )
        for f in definition.fields
    ]
    configured = any(values.get(f.key) for f in definition.fields)
    status = cred.status if cred and (configured or cred.status == "connected") else "not_configured"
    return ProviderOut(
        id=definition.id,
        name=definition.name,
        category=definition.category,
        purpose=definition.purpose,
        note=definition.note,
        fields=fields,
        configured=configured,
        status=status,
        status_detail=cred.status_detail if cred else None,
        last_tested_at=cred.last_tested_at if cred else None,
        secrets_rotated_at=cred.secrets_rotated_at if cred else None,
    )


def _check(provider_id: str) -> None:
    if provider_id not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")


@router.get("", response_model=list[ProviderOut])
def list_providers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [provider_out(db, user, p) for p in PROVIDERS]


@router.put("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str,
    data: ProviderIn,
    user: User = Depends(per_user("provider-save", 20)),
    db: Session = Depends(get_db),
):
    """Saves and tests. Replacing a working credential only takes effect if the new one passes the test."""
    _check(provider_id)
    # Masked values coming back from the UI mean "unchanged".
    values = {k: v for k, v in data.values.items() if not (v and v.startswith("•"))}
    try:
        await replace_credential(db, user, provider_id, values)
    except CredentialValidationError as exc:
        raise HTTPException(422, str(exc))
    return provider_out(db, user, provider_id)


@router.post("/{provider_id}/test", response_model=ProviderOut)
async def test_provider(
    provider_id: str, user: User = Depends(per_user("provider-test", 10)), db: Session = Depends(get_db)
):
    _check(provider_id)
    await test_connection(db, user, provider_id)
    return provider_out(db, user, provider_id)


@router.delete("/{provider_id}", response_model=ProviderOut)
def disconnect_provider(provider_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check(provider_id)
    cred = get_credential(db, user, provider_id)
    if cred:
        db.delete(cred)
        db.commit()
    return provider_out(db, user, provider_id)
