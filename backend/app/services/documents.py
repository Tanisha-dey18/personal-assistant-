"""Document ingestion: extract text → chunk → embed → (optionally) extract memories.
Only extracted text is kept (in the DB); the uploaded file itself is not stored."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from app.ai.provider import get_provider
from app.core.db import SessionLocal
from app.memory.extractor import extract_and_store
from app.memory.vectors import DOCUMENTS, vectors
from app.models import Document, DocumentChunk, ImportJob, User
from app.services.usage import log_usage

log = logging.getLogger("astra.documents")
ALLOWED = {".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".json", ".py", ".js", ".ts", ".html"}


def extract_text(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".docx":
        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    return data.decode("utf-8", errors="replace")


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    text = "\n".join(line.rstrip() for line in text.splitlines())
    chunks, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):  # try to break on a paragraph/sentence boundary
            for sep in ("\n\n", "\n", ". "):
                j = text.rfind(sep, i + size // 2, end)
                if j != -1:
                    end = j + len(sep)
                    break
        piece = text[i:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return chunks


async def ingest(user_id: str, doc_id: str, text: str, extract_memories: bool, job_id: str | None = None) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        job = await db.get(ImportJob, job_id) if job_id else None
        try:
            user = await db.get(User, user_id)
            provider = await get_provider(db, user_id)
            chunks = chunk_text(text)
            windows = [text[i:i + 6000] for i in range(0, min(len(text), 48000), 6000)] if extract_memories else []
            if job:
                job.status, job.total = "running", len(chunks) + len(windows) + 1
                await db.commit()
            for start in range(0, len(chunks), 64):
                batch = chunks[start:start + 64]
                vecs = await provider.embed(batch)
                rows = [DocumentChunk(document_id=doc_id, user_id=user_id, idx=start + k, content=c) for k, c in enumerate(batch)]
                db.add_all(rows)
                await db.flush()
                await vectors.upsert_many(DOCUMENTS, [(r.id, v, {"user_id": user_id, "document_id": doc_id}) for r, v in zip(rows, vecs)])
                if job:
                    job.progress += len(batch)
                await db.commit()
            summary, usage = await provider.complete([
                {"role": "system", "content": "Summarise this document in 3-5 sentences: what it is and the key points."},
                {"role": "user", "content": text[:12000]}])
            log_usage(db, user_id, "summary", usage)
            doc.summary = summary.strip()
            totals = {"created": 0, "updated": 0, "pending": 0, "questions": []}
            for w in windows:
                r = await extract_and_store(db, provider, user, w, kind="document", source="document", source_ref=doc.filename)
                for k in ("created", "updated", "pending"):
                    totals[k] += len(r[k])
                totals["questions"] += r["questions"]
                if job:
                    job.progress += 1
                    await db.commit()
            doc.status = "ready"
            if job:
                job.status, job.progress, job.result = "done", job.total, totals
            await db.commit()
        except Exception as e:  # noqa: BLE001
            log.exception("document ingest failed")
            await db.rollback()
            doc = await db.get(Document, doc_id)
            if doc:
                doc.status, doc.error = "failed", str(e)[:500]
            if job_id:
                job = await db.get(ImportJob, job_id)
                if job:
                    job.status, job.error = "failed", str(e)[:500]
            await db.commit()


async def delete_document(db, doc: Document) -> None:
    await vectors.delete_where(DOCUMENTS, doc.user_id, "document_id", doc.id)
    await db.delete(doc)
    await db.commit()
