"""Admin-managed IVR speech script templates (validated, persisted)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..schemas import SpeechScriptsPayload
from ..services import speech_script_service as ss
from ..services.speech_wav_cache import clear_all_speech_cache

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/speech-scripts", response_model=dict)
def get_speech_scripts(db: Session = Depends(get_db)) -> dict:
    ss.ensure_defaults_seeded(db)
    return ss.speech_scripts_response(db)


@router.put("/speech-scripts", response_model=dict)
def put_speech_scripts(body: SpeechScriptsPayload, db: Session = Depends(get_db)) -> dict:
    ss.ensure_defaults_seeded(db)
    try:
        ss.save_templates(db, body.scripts)
        if body.otp_digit_count is not None:
            ss.save_otp_digit_count(db, body.otp_digit_count)
        clear_all_speech_cache()
        return ss.speech_scripts_response(db)
    except ss.SpeechScriptValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/speech-scripts/reset", response_model=dict)
def reset_speech_scripts(db: Session = Depends(get_db)) -> dict:
    ss.reset_to_defaults(db)
    clear_all_speech_cache()
    return ss.speech_scripts_response(db)
