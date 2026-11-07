"""Documents, onboarding and knowledge imports."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import AIUnavailable, get_provider
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user, rate_limited_user
from app.models import Document, ImportJob, User
from app.services import documents as docsvc
from app.services import importer

router = APIRouter(prefix="/api", tags=["content"])
_tasks: set = set()


def _spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _require_ai(db, user):
    try:
        await get_provider(db, user.id)
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {settings.MAX_UPLOAD_MB} MB)")
    return data


def job_out(j: ImportJob) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "total": j.total, "result": j.result,
            "error": j.error, "created_at": j.created_at.isoformat() if j.created_at else None}


def doc_out(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "mime": d.mime, "size": d.size, "chars": d.chars, "status": d.status,
            "summary": d.summary, "error": d.error, "created_at": d.created_at.isoformat() if d.created_at else None}


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), extract_memories: bool = Form(False),
                          user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    await _require_ai(db, user)
    name = Path(file.filename or "upload.txt").name
    if Path(name).suffix.lower() not in docsvc.ALLOWED:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(docsvc.ALLOWED))}")
    data = await _read_upload(file)
    try:
        text = await asyncio.to_thread(docsvc.extract_text, data, name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Couldn't read that file: {e}") from e
    if len(text.strip()) < 20:
        raise HTTPException(422, "No readable text found (scanned PDFs need OCR first).")
    doc = Document(user_id=user.id, filename=name, mime=file.content_type or "", size=len(data), chars=len(text))
    job = ImportJob(user_id=user.id, kind="document")
    db.add_all([doc, job])
    await db.commit()
    _spawn(docsvc.ingest(user.id, doc.id, text, extract_memories, job.id))
    return {"document": doc_out(doc), "job": job_out(job)}


@router.get("/documents")
async def list_documents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc()))).scalars().all()
    return {"items": [doc_out(d) for d in rows]}


@router.delete("/documents/{did}")
async def delete_document(did: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await db.get(Document, did)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Not found")
    await docsvc.delete_document(db, d)
    return {"deleted": True}


@router.post("/import/chatgpt/preview")
async def chatgpt_preview(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    data = await _read_upload(file)
    try:
        convs = await asyncio.to_thread(importer.parse_chatgpt_export, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Couldn't parse export: {e}") from e
    return {"conversations": len(convs), "messages": sum(len(c["messages"]) for c in convs),
            "sample": [{"title": c["title"], "messages": len(c["messages"])} for c in convs[:15]]}


@router.post("/import/chatgpt")
async def chatgpt_import(file: UploadFile = File(...), max_conversations: int = Form(100), extract_memories: bool = Form(True),
                         user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    await _require_ai(db, user)
    data = await _read_upload(file)
    try:
        convs = await asyncio.to_thread(importer.parse_chatgpt_export, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Couldn't parse export: {e}") from e
    convs = convs[: max(1, min(max_conversations, 2000))]
    job = ImportJob(user_id=user.id, kind="chatgpt", total=len(convs))
    db.add(job)
    await db.commit()
    _spawn(importer.run_chatgpt_import(job.id, user.id, convs, extract_memories))
    return job_out(job)


class TextImportIn(BaseModel):
    text: str = Field(min_length=10, max_length=60000)
    label: str = Field(default="notes", max_length=120)


@router.post("/import/text")
async def text_import(body: TextImportIn, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    await _require_ai(db, user)
    job = ImportJob(user_id=user.id, kind="text")
    db.add(job)
    await db.commit()
    _spawn(importer.run_text_import(job.id, user.id, body.text, body.label))
    return job_out(job)


class OnboardingIn(BaseModel):
    name: str = ""
    location: str = ""
    education: str = ""
    current_focus: str = ""
    skills: str = ""
    interests: str = ""
    career_goals: str = ""
    projects: str = ""
    learning_style: str = ""
    about: str = ""
    timezone: str = ""


@router.post("/onboarding")
async def onboarding(body: OnboardingIn, user: User = Depends(rate_limited_user), db: AsyncSession = Depends(get_db)):
    try:
        provider = await get_provider(db, user.id)
    except AIUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if body.timezone:
        from app.services.user_settings import update_user_settings

        update_user_settings(user, {"timezone": body.timezone})
    if body.learning_style:
        from app.services.user_settings import update_user_settings

        update_user_settings(user, {"learning": {"style": body.learning_style}})
    created = await importer.apply_onboarding(db, provider, user, body.model_dump())
    return {"created": created}


@router.post("/onboarding/skip")
async def skip_onboarding(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.onboarded = True
    await db.commit()
    return {"ok": True}


@router.get("/jobs")
async def list_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ImportJob).where(ImportJob.user_id == user.id).order_by(ImportJob.created_at.desc()).limit(20))).scalars().all()
    return {"items": [job_out(j) for j in rows]}


@router.get("/jobs/{jid}")
async def get_job(jid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await db.get(ImportJob, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404, "Not found")
    return job_out(j)
