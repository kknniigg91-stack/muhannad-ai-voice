import os
import json
import httpx
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"
APPROVED_FILE = SAMPLES_DIR / "approved.json"
VOICE_MODEL_FILE = BASE_DIR / "voice_model.json"

HAKIM_API_URL = "https://api.tryhakim.ai"

def get_api_key():
    key = os.environ.get("HAKIM_API_KEY")
    if not key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("HAKIM_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise HTTPException(500, "مفتاح HAKIM_API_KEY غير موجود في .env")
    return key

class GenerateRequest(BaseModel):
    text: str

@router.post("/api/clone-voice-hakim")
async def clone_voice_hakim():
    if not APPROVED_FILE.exists():
        raise HTTPException(400, "لا توجد عينة معتمدة. اعتمد عينة أولاً.")
    meta = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
    filename = meta["filename"]
    sample_path = SAMPLES_DIR / filename
    if not sample_path.exists():
        raise HTTPException(404, "ملف العينة غير موجود على القرص.")
    
    api_key = get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    
    with open(sample_path, "rb") as f:
        files = {"audio_sample": (filename, f.read(), "audio/m4a")}
        data = {
            "name": "Muhannad Al-Tai",
            "consent_confirmed": "true",
            "language": "ar",
            "dialect": "iraqi"
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{HAKIM_API_URL}/v1/audio/voices", headers=headers, data=data, files=files)
    
    if r.status_code not in (200, 201):
        raise HTTPException(r.status_code, f"فشل استنساخ الصوت: {r.text}")
    
    result = r.json()
    voice_id = result.get("id") or result.get("voice_id") or result.get("data", {}).get("id")
    if not voice_id:
        raise HTTPException(500, f"استجابة غير متوقعة من Hakim: {result}")
    
    VOICE_MODEL_FILE.write_text(json.dumps({"voice_id": voice_id, "name": "Muhannad Al-Tai"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "voice_id": voice_id, "message": "تم استنساخ الصوت بنجاح عبر Hakim"}

@router.post("/api/generate-speech-hakim")
async def generate_speech_hakim(req: GenerateRequest):
    if not VOICE_MODEL_FILE.exists():
        raise HTTPException(400, "لا يوجد نموذج صوتي. استنسخ صوتك أولاً.")
    voice_id = json.loads(VOICE_MODEL_FILE.read_text()).get("voice_id")
    
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hakim-fast-v1",
        "voice": voice_id,
        "input": req.text
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{HAKIM_API_URL}/v1/audio/speech", headers=headers, json=payload)
    
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"فشل توليد الصوت: {r.text}")
    
    out_name = f"hakim_{hash(req.text) & 0xffffffff}.mp3"
    out_path = SAMPLES_DIR / out_name
    out_path.write_bytes(r.content)
    return {"ok": True, "audio_url": f"/api/sample/{out_name}", "filename": out_name, "size": len(r.content)}
