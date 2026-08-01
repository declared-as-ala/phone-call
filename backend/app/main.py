from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .config import get_cors_allowed_origins, validate_auth_configuration
from .services.luvvoice_tts import api_token_configured, default_voice_id
from .routers import auth, calls, simulator, speech_scripts, system, telephony, tts, websocket as ws
from .telephony_provider_config import (
    log_startup_configuration,
    validate_telephony_provider_configuration_on_startup,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    import logging

    validate_auth_configuration()
    provider_mode = validate_telephony_provider_configuration_on_startup()
    log_startup_configuration(provider_mode=provider_mode)
    if not api_token_configured():
        logging.getLogger(__name__).warning(
            "LUVVOICE_API_TOKEN is not set — premium speech will fail until you add it to "
            "backend/.env (LuvVoice Dashboard → API Tokens). Free system speech still works."
        )
    else:
        logging.getLogger(__name__).info(
            "LuvVoice TTS configured (default_voice_id=%s)", default_voice_id()
        )
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Outbound IVR Verification Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(calls.router, prefix="/api/calls", tags=["calls"])
app.include_router(simulator.router, prefix="/api/simulator", tags=["simulator"])
app.include_router(telephony.router, prefix="/api/telephony", tags=["telephony"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(speech_scripts.router, prefix="/api", tags=["speech-scripts"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(ws.router, tags=["websocket"])
