import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()
from groq import Groq
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Vera Bot", version="1.0.0")

# ─── In-memory stores ─────────────────────────────────────────────────────────
context_store: Dict[str, Dict] = {}
conversation_store: Dict[str, List[Dict]] = {}

# ─── Groq client ──────────────────────────────────────────────────────────────
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

MODEL = "llama-3.3-70b-versatile"   # free, fast, great at JSON

# ─── Pydantic models ──────────────────────────────────────────────────────────

class ContextRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str

class TickRequest(BaseModel):
    session_id: str
    merchant_id: str
    trigger_id: Optional[str] = None
    customer_id: Optional[str] = None
    ts: Optional[str] = None

class ReplyRequest(BaseModel):
    session_id: str
    merchant_id: str
    message: str
    ts: Optional[str] = None

# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Vera, magicpin's AI growth assistant for merchants in India.
Your job: compose the single best next message for a merchant that drives real action.

SCORING RUBRIC (judges measure all 5):
1. Decision quality   — pick the best signal for this exact moment (trigger + merchant state + category)
2. Specificity        — use real numbers, offer names, dates, local facts from the context given
3. Category fit       — match tone to business type:
   - dentist/clinic → clinical, trust-building, health-framed
   - salon/beauty   → aspirational, visual, trend-aware
   - restaurant     → sensory, timely, appetite-driven
   - gym/fitness    → motivational, streak-based, energy-forward
   - pharmacy       → utility, urgency, health-safety
4. Merchant fit       — personalize to THIS merchant's metrics, offers, locality, history
5. Engagement compulsion — one strong reason to reply NOW, single yes/no CTA

HARD RULES:
- One CTA per message only — never two options
- Never invent numbers not in the context
- Keep message under 160 characters if possible
- Sound like a knowledgeable business partner, not a bot
- Never say "Hi [name]" and immediately go generic

OUTPUT: Return ONLY a valid JSON object. No markdown fences, no explanation, just JSON.
{
  "message": "...",
  "cta": "...",
  "send_as": "vera",
  "suppression_key": "short-slug-for-dedup",
  "rationale": "1-2 sentences: why this message, this trigger, this moment"
}"""

# ─── Core logic ───────────────────────────────────────────────────────────────

def get_context(scope: str, context_id: str) -> Optional[Dict]:
    entry = context_store.get(f"{scope}:{context_id}")
    return entry["payload"] if entry else None


def build_prompt(
    merchant_id: str,
    trigger_id: Optional[str],
    customer_id: Optional[str],
    history: List[Dict],
    incoming_reply: Optional[str] = None,
) -> str:
    merchant = get_context("merchant", merchant_id) or {}
    trigger  = get_context("trigger", trigger_id) if trigger_id else None
    customer = get_context("customer", customer_id) if customer_id else None
    category = merchant.get("identity", {}).get("category", "general")

    parts = [f"CATEGORY: {category}"]
    parts.append(f"\nMERCHANT CONTEXT:\n{json.dumps(merchant, indent=2, ensure_ascii=False)}")

    if trigger:
        parts.append(f"\nTRIGGER:\n{json.dumps(trigger, indent=2, ensure_ascii=False)}")

    if customer:
        parts.append(f"\nCUSTOMER CONTEXT:\n{json.dumps(customer, indent=2, ensure_ascii=False)}")

    if history:
        parts.append(f"\nCONVERSATION HISTORY (last {min(5, len(history))} turns):")
        for turn in history[-5:]:
            parts.append(f"  [{turn.get('role','?')}]: {turn.get('content','')}")

    if incoming_reply:
        parts.append(f"\nMERCHANT JUST REPLIED: \"{incoming_reply}\"")
        parts.append("Compose Vera's best response grounded in the context above.")
    else:
        parts.append("\nCompose the best proactive message Vera should send right now.")

    return "\n".join(parts)


def compose(
    merchant_id: str,
    trigger_id: Optional[str],
    customer_id: Optional[str],
    history: List[Dict],
    incoming_reply: Optional[str] = None,
) -> Dict[str, Any]:
    prompt = build_prompt(merchant_id, trigger_id, customer_id, history, incoming_reply)

    try:
        resp = groq_client.chat.completions.create(
            model=MODEL,
            temperature=0.3,       # low temp = more deterministic
            max_tokens=400,
            response_format={"type": "json_object"},   # Groq supports this!
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "message": "I spotted an opportunity for your store — want me to act on it?",
            "cta": "Reply YES to see options",
            "send_as": "vera",
            "suppression_key": f"fallback-{merchant_id}",
            "rationale": "Fallback: JSON parse error.",
        }
    except Exception as e:
        result = {
            "message": "Something went wrong on our end. We'll retry shortly.",
            "cta": None,
            "send_as": "vera",
            "suppression_key": f"error-{merchant_id}",
            "rationale": str(e),
        }

    return result

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/v1/healthz")
def healthz():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/metadata")
def metadata():
    return {
        "name": "vera-bot",
        "version": "1.0.0",
        "model": MODEL,
        "provider": "groq",
        "author": "challenger",
        "description": "Vera — magicpin merchant growth assistant. Deterministic message composition from structured context.",
        "endpoints": ["/v1/healthz", "/v1/metadata", "/v1/context", "/v1/tick", "/v1/reply"],
    }


@app.post("/v1/context")
def receive_context(req: ContextRequest):
    key = f"{req.scope}:{req.context_id}"
    existing = context_store.get(key)

    if existing and existing["version"] == req.version:
        return {"accepted": False, "reason": "same_version", "ack_id": existing["ack_id"], "stored_at": existing["stored_at"]}

    if existing and existing["version"] > req.version:
        raise HTTPException(status_code=409, detail="Older version rejected")

    stored_at = datetime.now(timezone.utc).isoformat()
    ack_id = "ack_" + hashlib.md5(f"{key}:{req.version}:{stored_at}".encode()).hexdigest()[:10]

    context_store[key] = {
        "version": req.version,
        "payload": req.payload,
        "stored_at": stored_at,
        "ack_id": ack_id,
        "delivered_at": req.delivered_at,
    }

    return {"accepted": True, "ack_id": ack_id, "stored_at": stored_at}


@app.post("/v1/tick")
def tick(req: TickRequest):
    history = conversation_store.get(req.session_id, [])

    result = compose(
        merchant_id=req.merchant_id,
        trigger_id=req.trigger_id,
        customer_id=req.customer_id,
        history=history,
    )

    conversation_store.setdefault(req.session_id, []).append({
        "role": "vera",
        "content": result["message"],
        "ts": req.ts or datetime.now(timezone.utc).isoformat(),
    })

    return {"session_id": req.session_id, "merchant_id": req.merchant_id, **result,
            "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/v1/reply")
def reply(req: ReplyRequest):
    conversation_store.setdefault(req.session_id, []).append({
        "role": "merchant",
        "content": req.message,
        "ts": req.ts or datetime.now(timezone.utc).isoformat(),
    })

    history = conversation_store[req.session_id]

    result = compose(
        merchant_id=req.merchant_id,
        trigger_id=None,
        customer_id=None,
        history=history,
        incoming_reply=req.message,
    )

    conversation_store[req.session_id].append({
        "role": "vera",
        "content": result["message"],
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return {"session_id": req.session_id, "merchant_id": req.merchant_id, **result,
            "ts": datetime.now(timezone.utc).isoformat()}
