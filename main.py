import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()

from groq import Groq
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="Vera Bot", version="1.0.0")

context_store = {}
conversation_store = {}

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are Vera, magicpin's AI growth assistant for merchants in India.
Your job: compose the single best next message for a merchant that drives real action.

SCORING RUBRIC (judges measure all 5):
1. Decision quality   — pick the best signal for this exact moment (trigger + merchant state + category)
2. Specificity        — use real numbers, offer names, dates, local facts from the context given
3. Category fit       — match tone to business type:
   - dentist/clinic  → clinical, trust-building, health-framed
   - salon/beauty    → aspirational, visual, trend-aware
   - restaurant      → sensory, timely, appetite-driven
   - gym/fitness     → motivational, streak-based, energy-forward
   - pharmacy        → utility, urgency, health-safety
4. Merchant fit       — personalize to THIS merchant's metrics, offers, locality, history
5. Engagement compulsion — one strong reason to reply NOW, single yes/no CTA

HARD RULES:
- One CTA per message only
- Never invent numbers not in the context
- Keep message under 160 characters if possible
- Sound like a knowledgeable business partner, not a bot

OUTPUT: Return ONLY a valid JSON object. No markdown, no explanation.
{
  "message": "...",
  "cta": "...",
  "send_as": "vera",
  "suppression_key": "short-slug-for-dedup",
  "rationale": "1-2 sentences: why this message, this trigger, this moment"
}"""

def get_ctx(scope, context_id):
    entry = context_store.get(f"{scope}:{context_id}")
    return entry["payload"] if entry else None

def build_prompt(merchant_id, trigger_id, customer_id, history, incoming_reply=None):
    merchant = get_ctx("merchant", merchant_id) or {}
    trigger  = get_ctx("trigger", trigger_id) if trigger_id else None
    customer = get_ctx("customer", customer_id) if customer_id else None
    category = merchant.get("identity", {}).get("category", "general")
    parts = [f"CATEGORY: {category}"]
    parts.append(f"\nMERCHANT CONTEXT:\n{json.dumps(merchant, indent=2, ensure_ascii=False)}")
    if trigger:
        parts.append(f"\nTRIGGER:\n{json.dumps(trigger, indent=2, ensure_ascii=False)}")
    if customer:
        parts.append(f"\nCUSTOMER CONTEXT:\n{json.dumps(customer, indent=2, ensure_ascii=False)}")
    if history:
        parts.append(f"\nCONVERSATION HISTORY (last {min(5,len(history))} turns):")
        for t in history[-5:]:
            parts.append(f"  [{t.get('role','?')}]: {t.get('content','')}")
    if incoming_reply:
        parts.append(f"\nMERCHANT JUST REPLIED: \"{incoming_reply}\"")
        parts.append("Compose Vera's best response grounded in the context above.")
    else:
        parts.append("\nCompose the best proactive message Vera should send right now.")
    return "\n".join(parts)

def compose(merchant_id, trigger_id, customer_id, history, incoming_reply=None):
    prompt = build_prompt(merchant_id, trigger_id, customer_id, history, incoming_reply)
    try:
        resp = groq_client.chat.completions.create(
            model=MODEL, temperature=0.3, max_tokens=400,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
        )
        return json.loads(resp.choices[0].message.content.strip())
    except Exception as e:
        return {
            "message": "I spotted an opportunity for your store — want me to act on it?",
            "cta": "Reply YES to see options",
            "send_as": "vera",
            "suppression_key": f"fallback-{merchant_id}",
            "rationale": str(e),
        }

@app.get("/v1/healthz")
def healthz():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/v1/metadata")
def metadata():
    return {
        "name": "vera-bot", "version": "1.0.0", "model": MODEL,
        "provider": "groq", "author": "challenger",
        "description": "Vera — magicpin merchant growth assistant.",
        "endpoints": ["/v1/healthz", "/v1/metadata", "/v1/context", "/v1/tick", "/v1/reply"],
    }

@app.post("/v1/context")
async def receive_context(request: Request):
    req = await request.json()
    scope = req["scope"]; context_id = req["context_id"]
    version = req["version"]; payload = req["payload"]
    key = f"{scope}:{context_id}"
    existing = context_store.get(key)
    if existing and existing["version"] == version:
        return {"accepted": False, "reason": "same_version",
                "ack_id": existing["ack_id"], "stored_at": existing["stored_at"]}
    if existing and existing["version"] > version:
        raise HTTPException(status_code=409, detail="Older version rejected")
    stored_at = datetime.now(timezone.utc).isoformat()
    ack_id = "ack_" + hashlib.md5(f"{key}:{version}:{stored_at}".encode()).hexdigest()[:10]
    context_store[key] = {"version": version, "payload": payload,
                          "stored_at": stored_at, "ack_id": ack_id}
    return {"accepted": True, "ack_id": ack_id, "stored_at": stored_at}

@app.post("/v1/tick")
async def tick(request: Request):
    req = await request.json()
    session_id = req["session_id"]; merchant_id = req["merchant_id"]
    trigger_id = req.get("trigger_id"); customer_id = req.get("customer_id")
    history = conversation_store.get(session_id, [])
    result = compose(merchant_id, trigger_id, customer_id, history)
    conversation_store.setdefault(session_id, []).append(
        {"role": "vera", "content": result["message"], "ts": datetime.now(timezone.utc).isoformat()})
    return {"session_id": session_id, "merchant_id": merchant_id,
            **result, "ts": datetime.now(timezone.utc).isoformat()}

@app.post("/v1/reply")
async def reply(request: Request):
    req = await request.json()
    session_id = req["session_id"]; merchant_id = req["merchant_id"]; message = req["message"]
    conversation_store.setdefault(session_id, []).append(
        {"role": "merchant", "content": message, "ts": datetime.now(timezone.utc).isoformat()})
    history = conversation_store[session_id]
    result = compose(merchant_id, None, None, history, incoming_reply=message)
    conversation_store[session_id].append(
        {"role": "vera", "content": result["message"], "ts": datetime.now(timezone.utc).isoformat()})
    return {"session_id": session_id, "merchant_id": merchant_id,
            **result, "ts": datetime.now(timezone.utc).isoformat()}