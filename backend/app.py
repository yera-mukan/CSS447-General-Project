import asyncio
import io
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://library:library@db:5432/library"
    jwt_secret: str
    jwt_expiry_seconds: int = 3600
    cors_origins: str = "http://localhost:3000"
    ocr_base_url: str = "http://ocr-app:8884"
    ocr_timeout_seconds: float = 60
    ocr_connect_timeout_seconds: float = 5
    upload_max_bytes: int = 5 * 1024 * 1024
    upload_max_pixels: int = 6_000_000
    max_attempts: int = 3
    claim_lease_seconds: int = 90
    max_pending_per_user: int = 10
    max_pending_global: int = 50


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
passwords = PasswordHasher()
oauth = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
log = logging.getLogger("library")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    image_data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(64))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def db_session():
    with SessionLocal() as session:
        yield session


def get_user(token: str = Depends(oauth), db: Session = Depends(db_session)) -> User:
    try:
        uid = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"]).get("sub")
        user = db.get(User, uuid.UUID(uid))
    except (JWTError, ValueError, TypeError, AttributeError):
        user = None
    if user is None:
        raise HTTPException(
            401, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def doc_or_404(db: Session, doc_id: uuid.UUID, owner: User) -> Document:
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.owner_id == owner.id))
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def summary(d: Document) -> dict:
    return {
        k: getattr(d, k)
        for k in (
            "id",
            "title",
            "original_filename",
            "mime_type",
            "status",
            "attempts",
            "last_error",
            "created_at",
            "updated_at",
        )
    }


def detail(d: Document) -> dict:
    return summary(d) | {
        "extracted_text": d.extracted_text,
        "corrected_text": d.corrected_text,
        "processing_started_at": d.processing_started_at,
        "processed_at": d.processed_at,
    }


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class PatchDocument(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    corrected_text: str | None = None


def retry_delay(attempt: int) -> int:
    return (2, 10)[min(attempt - 1, 1)]


def claim_document(db: Session, now: datetime | None = None) -> tuple[uuid.UUID, str, bytes] | None:
    now = now or datetime.now(UTC)
    with db.begin():
        d = db.scalar(
            select(Document)
            .where(
                or_(
                    (Document.status == "queued") & (Document.next_attempt_at <= now),
                    (Document.status == "processing") & (Document.lease_expires_at < now),
                )
            )
            .order_by(Document.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if d is None:
            return None
        if d.status == "processing" and d.attempts >= settings.max_attempts:
            d.status, d.last_error, d.processed_at = "failed", "worker_interrupted", now
            d.claim_token = None
            return None
        d.status = "processing"
        d.attempts += 1
        d.claim_token = secrets.token_hex(24)
        d.lease_expires_at = now + timedelta(seconds=settings.claim_lease_seconds)
        d.processing_started_at = now
        return d.id, d.claim_token, d.image_data


async def process_one(client: httpx.AsyncClient) -> bool:
    with SessionLocal() as db:
        job = claim_document(db)
    if job is None:
        return False
    doc_id, token, image = job
    with SessionLocal() as db:
        d = db.get(Document, doc_id)
        filename, mime = d.original_filename, d.mime_type
    try:
        r = await client.post(
            "/tesseract",
            data={"options": json.dumps({"languages": ["eng"], "pageSegmentationMethod": 3})},
            files={"file": (filename, image, mime)},
        )
        r.raise_for_status()
        payload = r.json()["data"]
        if (
            not isinstance(payload["exit"], dict)
            or payload["exit"].get("code") != 0
            or payload["exit"].get("signal") is not None
            or not isinstance(payload.get("stdout"), str)
            or not payload["stdout"].strip()
            or not isinstance(payload.get("stderr"), str)
        ):
            raise ValueError("invalid_ocr_response")
        with SessionLocal.begin() as db:
            db.execute(
                update(Document)
                .where(
                    Document.id == doc_id,
                    Document.status == "processing",
                    Document.claim_token == token,
                )
                .values(
                    status="ready",
                    extracted_text=payload["stdout"],
                    last_error=None,
                    claim_token=None,
                    lease_expires_at=None,
                    processed_at=func.now(),
                )
            )
    except (httpx.TimeoutException, httpx.TransportError):
        await fail_job(doc_id, token, "ocr_unavailable", True)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        await fail_job(
            doc_id,
            token,
            "ocr_unavailable" if code == 429 or code >= 500 else "ocr_rejected",
            code == 429 or code >= 500,
        )
    except (ValueError, KeyError, TypeError):
        await fail_job(doc_id, token, "invalid_ocr_response", False)
    return True


async def fail_job(doc_id: uuid.UUID, token: str, error: str, transient: bool) -> None:
    with SessionLocal.begin() as db:
        d = db.scalar(
            select(Document).where(
                Document.id == doc_id,
                Document.status == "processing",
                Document.claim_token == token,
            )
        )
        if d is None:
            return
        if transient and d.attempts < settings.max_attempts:
            d.status, d.next_attempt_at = (
                "queued",
                datetime.now(UTC) + timedelta(seconds=retry_delay(d.attempts)),
            )
        else:
            d.status, d.processed_at = "failed", datetime.now(UTC)
        d.last_error, d.claim_token, d.lease_expires_at = error, None, None


async def worker_loop():
    timeout = httpx.Timeout(
        settings.ocr_timeout_seconds, connect=settings.ocr_connect_timeout_seconds
    )
    async with httpx.AsyncClient(
        base_url=settings.ocr_base_url.rstrip("/"), timeout=timeout
    ) as client:
        while True:
            if not await process_one(client):
                await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(worker_loop()) if app.state.run_worker else None
    yield
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="CSS447 Document Library", version="0.1.0", lifespan=lifespan)
app.state.run_worker = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(db: Session = Depends(db_session)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ok"}


@app.post("/api/v1/auth/register", status_code=201)
def register(body: Credentials, db: Session = Depends(db_session)):
    email = str(body.email).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    user = User(email=email, password_hash=passwords.hash(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@app.post("/api/v1/auth/login")
def login(body: Credentials, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    try:
        valid = user is not None and passwords.verify(user.password_hash, body.password)
    except VerifyMismatchError:
        valid = False
    if not valid:
        raise HTTPException(401, "Invalid email or password")
    token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(UTC) + timedelta(seconds=settings.jwt_expiry_seconds),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expiry_seconds,
    }


@app.get("/api/v1/auth/me")
def me(user: User = Depends(get_user)):
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@app.post("/api/v1/documents", status_code=202)
async def upload(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    user: User = Depends(get_user),
    db: Session = Depends(db_session),
):
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        raise HTTPException(413, "Image too large")
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in ("JPEG", "PNG"):
            raise HTTPException(415, "Only JPEG and PNG are supported")
        if (
            image.width * image.height > settings.upload_max_pixels
            or getattr(image, "n_frames", 1) != 1
        ):
            raise HTTPException(422, "Image dimensions or animation are unsupported")
        image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(422, "Invalid image")
    name = Path(file.filename or "page").name[:255]
    mime = "image/jpeg" if image.format == "JPEG" else "image/png"
    from sqlalchemy import text as sql_text

    with db.begin_nested():
        db.execute(sql_text("SELECT pg_advisory_xact_lock(7447)"))
        pending = (
            select(func.count())
            .select_from(Document)
            .where(Document.status.in_(["queued", "processing"]))
        )
        user_pending = db.scalar(pending.where(Document.owner_id == user.id)) or 0
        all_pending = db.scalar(pending) or 0
        if (
            user_pending >= settings.max_pending_per_user
            or all_pending >= settings.max_pending_global
        ):
            raise HTTPException(429, "Pending document limit reached")
        d = Document(
            owner_id=user.id,
            title=(title or Path(name).stem)[:255],
            original_filename=name,
            mime_type=mime,
            image_data=raw,
        )
        db.add(d)
        db.flush()
    db.commit()
    db.refresh(d)
    return summary(d)


@app.get("/api/v1/documents")
def list_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_user),
    db: Session = Depends(db_session),
):
    rows = db.scalars(
        select(Document)
        .where(Document.owner_id == user.id)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    return {"items": [summary(d) for d in rows]}


@app.get("/api/v1/documents/search")
def search(
    q: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_user),
    db: Session = Depends(db_session),
):
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    effective = func.coalesce(Document.corrected_text, Document.extracted_text)
    rows = db.scalars(
        select(Document)
        .where(
            Document.owner_id == user.id,
            Document.status == "ready",
            effective.ilike(pattern, escape="\\"),
        )
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    items = []
    for d in rows:
        item = summary(d)
        effective_text = (
            d.corrected_text if d.corrected_text is not None else d.extracted_text or ""
        )
        match = effective_text.casefold().find(q.casefold())
        start = max(0, match - 60)
        end = min(len(effective_text), start + 160)
        item["snippet"] = (
            ("…" if start else "")
            + effective_text[start:end]
            + ("…" if end < len(effective_text) else "")
        )
        items.append(item)
    return {"items": items}


@app.get("/api/v1/documents/{doc_id}")
def get_document(
    doc_id: uuid.UUID, user: User = Depends(get_user), db: Session = Depends(db_session)
):
    return detail(doc_or_404(db, doc_id, user))


@app.get("/api/v1/documents/{doc_id}/image")
def get_image(doc_id: uuid.UUID, user: User = Depends(get_user), db: Session = Depends(db_session)):
    d = doc_or_404(db, doc_id, user)
    return Response(d.image_data, media_type=d.mime_type, headers={"Cache-Control": "no-store"})


@app.patch("/api/v1/documents/{doc_id}")
def patch_document(
    doc_id: uuid.UUID,
    body: PatchDocument,
    user: User = Depends(get_user),
    db: Session = Depends(db_session),
):
    d = doc_or_404(db, doc_id, user)
    changes = body.model_fields_set
    if "corrected_text" in changes and d.status != "ready":
        raise HTTPException(409, "Text can only be corrected after OCR completes")
    if "title" in changes:
        if body.title is None:
            raise HTTPException(422, "Title cannot be null")
        d.title = body.title
    if "corrected_text" in changes:
        d.corrected_text = body.corrected_text
    db.commit()
    db.refresh(d)
    return detail(d)


@app.post("/api/v1/documents/{doc_id}/retry", status_code=202)
def retry(doc_id: uuid.UUID, user: User = Depends(get_user), db: Session = Depends(db_session)):
    d = doc_or_404(db, doc_id, user)
    if d.status != "failed":
        raise HTTPException(409, "Only failed documents can be retried")
    d.status, d.attempts, d.last_error = "queued", 0, None
    d.next_attempt_at, d.processed_at = datetime.now(UTC), None
    db.commit()
    db.refresh(d)
    return summary(d)


@app.get("/api/v1/documents/{doc_id}/export")
def export(doc_id: uuid.UUID, user: User = Depends(get_user), db: Session = Depends(db_session)):
    d = doc_or_404(db, doc_id, user)
    if d.status != "ready":
        raise HTTPException(409, "Document is not ready")
    safe = d.title.replace('"', "")[:100] or "document"
    return Response(
        d.corrected_text if d.corrected_text is not None else d.extracted_text or "",
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}.txt"',
            "Cache-Control": "no-store",
        },
    )


@app.delete("/api/v1/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: uuid.UUID, user: User = Depends(get_user), db: Session = Depends(db_session)
):
    d = doc_or_404(db, doc_id, user)
    db.delete(d)
    db.commit()
