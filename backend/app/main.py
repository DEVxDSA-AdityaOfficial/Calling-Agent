import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .retell_client import RetellError
from .routers import agents, auth, calls, llm_ws, meta, providers, speech, twilio_media, webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Calling Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RetellError)
async def retell_error_handler(request: Request, exc: RetellError):
    # Raised e.g. when Retell isn't connected; surface it instead of a bare 500.
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(auth.router)
app.include_router(meta.router)
app.include_router(providers.router)
app.include_router(speech.router)
app.include_router(twilio_media.router)
app.include_router(agents.router)
app.include_router(calls.router)
app.include_router(webhooks.router)
app.include_router(llm_ws.router)
