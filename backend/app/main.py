"""JARVIS backend entrypoint.  Run:  uvicorn app.main:app --reload"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, content, memory, productivity, system
from app.core.config import settings
from app.core.db import init_db
from app.memory.vectors import vectors
from app.services import proactive

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("astra")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if vectors.client is None:
        await vectors.init()
    stop = asyncio.Event()
    task = asyncio.create_task(proactive.loop(stop)) if settings.PROACTIVE_INTERVAL_SECONDS > 0 else None
    if not settings.OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY is not set — users must add a key in Settings → API before chatting.")
    log.info("JARVIS online.")
    yield
    stop.set()
    if task:
        await task
    await vectors.close()


app = FastAPI(title="JARVIS API", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs" if settings.ENV != "production" else None, openapi_url="/api/openapi.json")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error — check the server logs."}, status_code=500)


for r in (auth.router, chat.router, memory.router, productivity.router, content.router, system.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    return {"status": "ok", "name": "JARVIS", "tagline": "Your mind, extended."}
