"""Runtime/debug endpoints for the dashboard. Admin auth required; never returns secrets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_admin
from ..schemas import SipUpAccountSettingsRead, SipUpAccountSettingsUpdate
from ..services.sip_up_settings_store import get_public_settings, update_settings
from ..telephony_provider_config import runtime_provider_info

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/runtime", response_model=dict)
def runtime_config() -> dict[str, Any]:
    """Return resolved telephony provider state for the dashboard badge and runbooks.

    Booleans like ``asterisk.password_present`` indicate whether a credential is
    configured without disclosing it.
    """
    return runtime_provider_info()


@router.get("/sip-up-account", response_model=SipUpAccountSettingsRead)
def get_sip_up_account_settings() -> SipUpAccountSettingsRead:
    """Return SIP UP account settings for the dashboard (no password)."""
    return SipUpAccountSettingsRead.model_validate(get_public_settings())


@router.put("/sip-up-account", response_model=dict)
def put_sip_up_account_settings(body: SipUpAccountSettingsUpdate) -> dict[str, Any]:
    """Update SIP UP account from the dashboard (persists locally, syncs infra when possible)."""
    try:
        result = update_settings(
            label=body.label,
            sip_username=body.sip_username,
            sip_password=body.sip_password,
            sip_domain=body.sip_domain,
            sip_port=body.sip_port,
            outbound_caller_id=body.outbound_caller_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **result}
