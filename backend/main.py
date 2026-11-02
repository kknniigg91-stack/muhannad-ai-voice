"""Muhannad AI Voice - Backend API
Phase 2: Voice sample upload + approval (no voice cloning yet).
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"
SAMPLES_DIR.mkdir(exist_ok=True)
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
APPROVED_FILE = SAMPLES_DIR / "approved.json"

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac", ".opus"}
MAX_SIZE = 25 * 1024 * 1024  # 25 MB

app = FastAPI(title="Muhannad AI Voice API", version="0.3.0")
import voice_clone
import ai_chat
app.include_router(voice_clone.router)
app.include_router(ai_chat.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_name(name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise HTTPException(400, "اسم ملف غير صالح")
    p = (SAMPLES_DIR / name).resolve()
    try:
        p.relative_to(SAMPLES_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "مسار غير صالح")
    return p


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Muhannad AI Voice", "version": "0.2.0"}


@app.get("/api/voice-status")
def voice_status():
    files = [f for f in SAMPLES_DIR.iterdir() if f.is_file() and f.suffix.lower() in ALLOWED_EXT]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    approved = None
    if APPROVED_FILE.exists():
        try:
            approved = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
        except Exception:
            approved = None
    return {
        "samples_count": len(files),
        "has_sample": len(files) > 0,
        "latest": files[0].name if files else None,
        "approved": approved is not None,
        "approved_meta": approved,
    }


@app.post("/api/upload-voice")
async def upload_voice(file: UploadFile = File(...)):
    orig = file.filename or "voice"
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"صيغة غير مدعومة: {ext}. المسموح: {', '.join(sorted(ALLOWED_EXT))}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"sample_{ts}_{uuid.uuid4().hex[:6]}{ext}"
    dest = SAMPLES_DIR / name
    size = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SIZE:
                    raise HTTPException(413, f"حجم الملف يتجاوز {MAX_SIZE // (1024 * 1024)} ميجابايت")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"خطأ في حفظ الملف: {e}")
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "الملف فارغ")
    return {"ok": True, "filename": name, "size": size, "url": f"/api/sample/{name}"}


@app.post("/api/approve-voice")
async def approve_voice(payload: dict):
    name = (payload or {}).get("filename")
    if not name:
        raise HTTPException(400, "حقل filename مطلوب")
    p = _safe_name(name)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "الملف غير موجود")
    meta = {
        "filename": name,
        "size": p.stat().st_size,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    APPROVED_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "approved": meta}


@app.get("/api/sample/{name}")
def get_sample(name: str):
    p = _safe_name(name)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(p)


@app.delete("/api/sample/{name}")
def delete_sample(name: str):
    p = _safe_name(name)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "الملف غير موجود")
    p.unlink()
    if APPROVED_FILE.exists():
        try:
            meta = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
            if meta.get("filename") == name:
                APPROVED_FILE.unlink()
        except Exception:
            pass
    return {"ok": True}


# Mount frontend LAST so /api/* routes take precedence
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")