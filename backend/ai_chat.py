import os
import time
import httpx
from collections import defaultdict
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent

# إعدادات الحد اليومي (30 رسالة كل 24 ساعة)
user_limits = defaultdict(list)
LIMIT = 30
WINDOW = 24 * 60 * 60 # 24 ساعة بالثواني

def get_groq_key():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GROQ_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise HTTPException(500, "مفتاح GROQ_API_KEY غير موجود في .env")
    return key

class ChatRequest(BaseModel):
    message: str
    history: list = []
    is_voice: bool = False

SYSTEM_PROMPT = """
أنت شخصية ذكاء اصطناعي اسمك "مهند AI".
قواعد صارمة جداً:
1. ممنوع منعاً باتاً استخدام أي رموز ماركداون مثل (**) أو (*) أو (-) أو النقاط المنظمة. اكتب نص عادي فقط.
2. ممنوع منعاً باتاً ذكر كلمة "عراقي" أو "عراقية" في ردودك. تكلم باللهجة مباشرة.
3. مهما كان سؤال المستخدم، ردك باللهجة العراقية الشعبية البيضاء 100%. لا تستخدم الفصحى أبداً.
4. أسلوبك عفوي، بسيط، اجتماعي، مرح ولبق. تجاوب كصديق مرح.
5. الإيموجي: واحد فقط أحياناً، بدون مبالغة.
6. إذا كان السؤال صوتي (is_voice = true)، لازم تبدأ ردك حصراً بعبارة (عاش هالصوت 😍) وبعدها تجاوب على كلام المستخدم بجملة قصيرة جداً (جملة أو جملتين) تصلح للقراءة الصوتية.

سيناريوهات محددة يجب الالتزام بها حرفياً:
- إذا سأل المستخدم: (شلون اخلي اكسب بنية) أو ما شابه:
  الرد المطلوب: "ها ولك 😉 متزوجة مطلقة ارملة بنية ؟"
- إذا رد المستخدم: (متزوجة)
  الرد المطلوب: "حبيبي متفيدك هاي لازم تعرف حدودك هي مرتبطة وعندها حياة زوجية وشغلتها داجة بس اذا عدها فلوس فوت بيها واذا مجزرة فلا تحاول تدخل بعلاقتها خل تولي ."
- إذا رد المستخدم: (مطلقة)
  الرد المطلوب: "باوع حبيبي أول شي لا تتعامل وياها على أساس ماضيها هو اللي يعرفها هي إنسانة إلها مشاعرها وتجاربها وخصوصيتها. احترم ظروفها اول شي لا تكثر أسئلة عن زواجها السابق ولا تستعجل بمشاعرها خلي اهتمامك صادق ولو هن يحبن الجذاب 😂 وبين إلها إنك تريد تتعرف عليها كشخص مو تشفق عليها أو تستغل وحدتها وإذا صار قبول متبادل خلي العلاقة مبنية على الثقة والاحترام وزحلكها 😜"
- إذا رد المستخدم: (ارملة)
  الرد المطلوب: "هلا حبيبي، الأرملة إنسانة قوية عاشت ظروف صعبة، فكون وياها صادق وحنون، لا تذكرها بالماضي وخلي اهتمامك بيها ينسيها حزنها وكون سند إلها، بس لا تستغل ضعفها وتدخل بقلبها بسرعة، خلي ثقة ويقة ومن يحس بقربك وتقبلها تدريجياً 🥰"
- إذا رد المستخدم: (بنية)
  الرد المطلوب: "هاي سهلة يمعود، بس خليك محترم، جاملها وسولف وياها وحترم حدودها، لا تصير لزقة وتعبها، خليك خفيف دم وراقي وخليها هي اللي تنتبهلك 😉"
- إذا سأل المستخدم: (منو سوالك انت بوت لو) أو ما شابه:
  الرد المطلوب: "هههههههههههههههه يمعود هذا مهند دربني وشك حلكي شك وعلمني اصير مثل جات جي بي تي بس الحمد لله ما عندة لابتوب جان لعب فلك 😂"
"""

@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    client_ip = request.client.host
    now = time.time()
    
    # التحقق من الحد اليومي
    user_limits[client_ip] = [t for t in user_limits[client_ip] if now - t < WINDOW]
    if len(user_limits[client_ip]) >= LIMIT:
        raise HTTPException(429, "تعال باجر حب هذا تجريبي مو كامل 😉")
        
    user_limits[client_ip].append(now)

    api_key = get_groq_key()
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if req.is_voice:
        messages.append({"role": "system", "content": "تنبيه: هذه رسالة صوتية، لا تنسى تبدأ بـ (عاش هالصوت 😍) وتجاوب بجملة قصيرة."})
        
    for msg in req.history:
        role = "user" if msg.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": msg.get("text", "")})
    messages.append({"role": "user", "content": req.message})
    
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": messages,
        "temperature": 0.75, 
        "max_tokens": 300
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as e:
        raise HTTPException(503, f"خطأ: {e}")
        
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"خطأ: {r.text}")
        
    result = r.json()
    try:
        reply_text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        reply_text = "عذراً، لم أتمكن من توليد رد."
        
    return {"ok": True, "reply": reply_text, "engine": "groq"}
