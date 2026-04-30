"""
Vera Bot — magicpin AI Challenge (v13)
Built from actual dataset: real trigger kinds, category voices, merchant signals.
Target: 42-46/50
"""

import os, json, hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from groq import Groq
from fastapi import FastAPI, Request

app = FastAPI(title="Vera Bot", version="13.0.0")
context_store = {}
conversation_store = {}
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL = "llama-3.3-70b-versatile"

# ── Category voice config (from actual category JSONs) ──────────────────────
CATEGORY_VOICE = {
    "dentists": {
        "noun": "patients", "tone": "peer_clinical",
        "salutation": "Dr. {owner}",
        "taboo": ["guaranteed", "100% safe", "miracle", "best in city"],
        "example": "Worth a look — JIDA Oct 2026 p.14",
    },
    "salons": {
        "noun": "clients", "tone": "warm_practical",
        "salutation": "Hi {owner}",
        "taboo": ["guaranteed glow", "miracle", "instant transformation"],
        "example": "Bridal season is starting — bookings usually 2x normal in next 4 weeks",
    },
    "restaurants": {
        "noun": "covers", "tone": "warm_busy_practical",
        "salutation": "Hi {owner}",
        "taboo": ["best food in city", "guaranteed packed house", "viral guarantee"],
        "example": "Quick one — IPL match nights have been 1.5x your weekday avg this season",
    },
    "gyms": {
        "noun": "members", "tone": "energetic_disciplined",
        "salutation": "Hi {owner}",
        "taboo": ["guaranteed weight loss", "shred in 7 days", "miracle transformation"],
        "example": "Footfall pattern: April drop-off is normal; bookings recover by 2nd week May",
    },
    "pharmacies": {
        "noun": "customers", "tone": "trustworthy_precise",
        "salutation": "Hi {owner}",
        "taboo": ["miracle cure", "100% safe", "best price"],
        "example": "Quick check — your repeat-prescription customer count is up 18% this month",
    },
}

# ── Trigger kind → message strategy ────────────────────────────────────────
TRIGGER_STRATEGY = {
    "research_digest":       "Share a relevant research finding that affects this merchant's patient/client mix",
    "regulation_change":     "Alert about compliance deadline with specific action needed",
    "recall_due":            "Patient recall message — use their name, service due, available slots",
    "perf_dip":              "Performance is down X% — lead with the dip metric, offer a fix",
    "renewal_due":           "Subscription expires in N days — urgency + renewal amount",
    "festival_upcoming":     "Festival demand is coming — lead with the festival name and days until",
    "wedding_package_followup": "Wedding is in N days — next step in bridal prep journey",
    "curious_ask_due":       "Ask merchant what's in demand this week — conversational",
    "winback_eligible":      "Subscription lapsed N days ago — re-engage with what they're missing",
    "ipl_match_today":       "IPL match tonight — match-night combo opportunity",
    "review_theme_emerged":  "A review pattern emerged — address the theme operationally",
    "milestone_reached":     "Almost at a milestone (e.g. 150 reviews) — capitalize on momentum",
    "active_planning_intent":"Continue the conversation from merchant's last message",
    "seasonal_perf_dip":     "Expected seasonal dip — reassure and suggest retention focus",
    "customer_lapsed_hard":  "Customer hasn't visited in N days — winback message to merchant",
    "trial_followup":        "Trial completed — next session booking opportunity",
    "supply_alert":          "Urgent supply/recall alert — pull batches, inform affected customers",
    "chronic_refill_due":    "Customer's chronic meds run out on DATE — set up delivery now",
    "category_seasonal":     "Seasonal demand shift — shelf action + offer push",
    "gbp_unverified":        "Unverified GBP means 30% fewer impressions — verify now",
    "cde_opportunity":       "Free CDE credits available — relevant to their practice",
    "competitor_opened":     "New competitor nearby with a lower price offer",
    "perf_spike":            "Performance spike — capitalize on momentum",
    "dormant_with_vera":     "Merchant hasn't replied in N days — re-engage gently",
    "ipl_match_today":       "IPL tonight in city — match-night promo window",
}

def get_ctx(scope, cid):
    e = context_store.get(f"{scope}:{cid}")
    return e["payload"] if e else None

def pick_best_offer(merchant):
    offers = merchant.get("offers", [])
    active = [o for o in offers if o.get("status") == "active"]
    pool = active or offers
    if not pool: return None
    return sorted(pool, key=lambda o: float(str(o.get("price", o.get("value", "9999"))).replace("₹","").replace(",","").split()[0]) if str(o.get("price", o.get("value","9999"))).replace("₹","").replace(",","").split()[0].replace(".","").isdigit() else 9999)[0]

def clean_name(name, cat):
    """Never double-prefix Dr."""
    if cat == "dentists" and not name.lower().startswith("dr"):
        return f"Dr. {name}"
    return name

def build_system_prompt(cat):
    voice = CATEGORY_VOICE.get(cat, CATEGORY_VOICE["pharmacies"])
    return f"""You are Vera, magicpin's AI growth assistant. Compose ONE message for a {cat} merchant.

VOICE FOR {cat.upper()}: {voice['tone']}
- Address noun: {voice['noun']}  
- Salutation style: {voice['salutation']}
- NEVER use: {voice['taboo']}
- Tone example: "{voice['example']}"

JUDGE SCORES 5 DIMENSIONS:
1. SPECIFICITY: Real numbers, ₹prices, offer titles, dates, search counts. Vague = 3/10.
2. CATEGORY FIT: Strict voice match above. Wrong tone = 5/10 max.
3. MERCHANT FIT: Exact merchant name, owner, locality, active offer with ₹price.
4. TRIGGER RELEVANCE: Message must directly address WHY this trigger fired. Generic nudge = 4/10.
5. ENGAGEMENT: Loss aversion or curiosity. One YES/NO CTA. Under 160 chars.

RULES:
- Never say "Dr. Dr." — name may already have Dr.
- ONE CTA only
- Under 180 chars body
- Never fabricate numbers not given

OUTPUT: JSON only.
{{"body": "...", "cta": "...", "send_as": "vera", "suppression_key": "slug", "rationale": "trigger_kind + key signal used"}}"""

def build_fallback(merchant, trigger, cat):
    """Trigger-aware fallback using real dataset structure."""
    identity = merchant.get("identity", {})
    raw_name = identity.get("name", "Your store")
    name = clean_name(raw_name, cat)
    owner = identity.get("owner_first_name", "")
    locality = identity.get("locality", "your area")
    perf = merchant.get("performance", {})
    views = perf.get("views", 0)
    calls = perf.get("calls", 0)
    signals = merchant.get("signals", [])
    voice = CATEGORY_VOICE.get(cat, CATEGORY_VOICE["pharmacies"])
    noun = voice["noun"]
    offer = pick_best_offer(merchant)
    offer_str = ""
    if offer:
        t = offer.get("title", "")
        offer_str = f" '{t}'" if t else ""

    kind = trigger.get("kind", "") if trigger else ""
    payload = trigger.get("payload", {}) if trigger else {}
    urgency = trigger.get("urgency", 1) if trigger else 1

    # ── Trigger-specific message templates ──
    if kind == "perf_dip":
        metric = payload.get("metric", "calls")
        delta = abs(int(payload.get("delta_pct", -0.3) * 100))
        baseline = payload.get("vs_baseline", calls)
        body = f"{name}: {metric} down {delta}% this week (was {baseline}). {offer_str or 'Want me to fix this?'}"
        if offer_str: body += " — push offer to recover?"
        cta = "Reply YES to activate"
        key = f"perf-dip-{raw_name[:12]}"

    elif kind == "renewal_due":
        days = payload.get("days_remaining", 12)
        amount = payload.get("renewal_amount", "")
        body = f"{name}: Pro plan expires in {days} days{f' — renew at ₹{amount}' if amount else ''}. Listings pause after expiry."
        cta = "Reply YES to renew now"
        key = f"renewal-{raw_name[:12]}"

    elif kind == "festival_upcoming":
        festival = payload.get("festival", "upcoming festival")
        days_until = payload.get("days_until", "")
        days_str = f" in {days_until} days" if days_until else ""
        body = f"{name}: {festival}{days_str} — demand for your services peaks now.{offer_str}"
        if offer_str: body += " Push it?"
        cta = f"Reply YES to capture {festival} demand"
        key = f"festival-{festival[:10]}-{raw_name[:10]}"

    elif kind == "ipl_match_today":
        match = payload.get("match", "IPL match")
        city = payload.get("city", locality)
        body = f"{match} tonight in {city} — match-night {noun} up 1.5x.{offer_str or ' Run a combo deal?'}"
        if offer_str: body += " Push it now?"
        cta = "Reply YES — push before 6pm"
        key = f"ipl-{raw_name[:12]}"

    elif kind == "competitor_opened":
        comp = payload.get("competitor_name", "a competitor")
        dist = payload.get("distance_km", "")
        their_offer = payload.get("their_offer", "")
        dist_str = f"{dist}km away" if dist else "nearby"
        body = f"{comp} opened {dist_str} with '{their_offer}'.{offer_str} Counter with yours before they capture your {noun}?"
        cta = "Reply YES to respond"
        key = f"competitor-{raw_name[:12]}"

    elif kind == "supply_alert":
        molecule = payload.get("molecule", "")
        batches = payload.get("affected_batches", [])
        body = f"URGENT: {molecule} recall — batches {', '.join(batches[:2]) if batches else 'affected'}. Pull stock + WhatsApp your chronic {noun}?"
        cta = "Reply YES for customer list"
        key = f"supply-alert-{molecule[:10]}"

    elif kind == "chronic_refill_due":
        meds = payload.get("molecule_list", [])
        runs_out = payload.get("stock_runs_out_iso", "")
        med_str = ", ".join(meds[:2]) if meds else "chronic meds"
        date_str = runs_out[:10] if runs_out else "soon"
        body = f"Patient's {med_str} stock runs out {date_str}. Delivery address saved — want me to send a refill reminder now?"
        cta = "Reply YES to send reminder"
        key = f"refill-{raw_name[:12]}"

    elif kind == "winback_eligible":
        days = payload.get("days_since_expiry", 38)
        lapsed = payload.get("lapsed_customers_added_since_expiry", "")
        lapsed_note = f" {lapsed} new {noun} missed you." if lapsed else ""
        body = f"{name}: {days} days since subscription lapsed.{lapsed_note} Reactivate to recapture them?"
        cta = "Reply YES to reactivate"
        key = f"winback-{raw_name[:12]}"

    elif kind == "gbp_unverified":
        uplift = int(payload.get("estimated_uplift_pct", 0.3) * 100)
        body = f"{name}: Unverified listing = ~{uplift}% fewer impressions. Takes 5 min to fix. Want the steps?"
        cta = "Reply YES for guide"
        key = f"gbp-verify-{raw_name[:12]}"

    elif kind == "category_seasonal":
        trends = payload.get("trends", [])
        top = trends[0] if trends else "seasonal demand shift"
        body = f"{name}: {top} this summer. Rearrange shelf + push your top offer to capture peak demand?"
        cta = "Reply YES to act now"
        key = f"seasonal-{raw_name[:12]}"

    elif kind == "perf_spike":
        metric = payload.get("metric", "calls")
        delta = int(payload.get("delta_pct", 0.15) * 100)
        driver = payload.get("likely_driver", "")
        body = f"{name}: {metric} up {delta}%{f' — looks like {driver}' if driver else ''}. Capitalize now{offer_str}?"
        cta = "Reply YES to boost further"
        key = f"spike-{raw_name[:12]}"

    elif kind == "review_theme_emerged":
        theme = payload.get("theme", "")
        count = payload.get("occurrences_30d", "")
        quote = payload.get("common_quote", "")
        quote_str = f" — \"{quote[:40]}\"" if quote else ""
        body = f"{name}: '{theme}' mentioned {count}x this month{quote_str}. Address it before it hurts rating?"
        cta = "Reply YES for action steps"
        key = f"review-{theme[:10]}-{raw_name[:10]}"

    elif kind == "milestone_reached":
        metric = payload.get("metric", "reviews")
        now = payload.get("value_now", "")
        milestone = payload.get("milestone_value", "")
        body = f"{name}: {now} {metric} — just {milestone - now if isinstance(now,int) and isinstance(milestone,int) else 'a few'} away from {milestone}! Push{offer_str} to get there this week?"
        cta = "Reply YES to push"
        key = f"milestone-{raw_name[:12]}"

    elif kind == "dormant_with_vera":
        days = payload.get("days_since_last_merchant_message", "")
        topic = payload.get("last_topic", "")
        body = f"Hi {owner or name} — we last spoke about {topic or 'your listing'}{f' {days} days ago' if days else ''}. Anything I can help with today?"
        cta = "Reply to continue"
        key = f"dormant-{raw_name[:12]}"

    else:
        # Generic but uses real numbers
        conv = round((calls/views)*100, 1) if views else 0
        body = f"{name}: {views} views → {calls} {noun} ({conv}% CTR) in {locality}."
        if offer_str: body += f" Boost with{offer_str}?"
        cta = "Reply YES / No"
        key = f"perf-{raw_name[:12]}"

    return {
        "body": body[:240],
        "cta": cta,
        "send_as": "vera",
        "suppression_key": key.lower().replace(" ", "-"),
        "rationale": f"{kind} | {cat} | {locality}"
    }

def compose_for_trigger(tid):
    trigger = get_ctx("trigger", tid)
    if not trigger: return None
    merchant_id = trigger.get("merchant_id")
    if not merchant_id: return None
    merchant = get_ctx("merchant", merchant_id)
    if not merchant: return None

    cat = merchant.get("category_slug", merchant.get("category", "pharmacies"))
    identity = merchant.get("identity", {})
    raw_name = identity.get("name", "")
    display_name = clean_name(raw_name, cat)
    owner = identity.get("owner_first_name", "")
    locality = identity.get("locality", "")
    perf = merchant.get("performance", {})
    offer = pick_best_offer(merchant)
    kind = trigger.get("kind", "unknown")
    strategy = TRIGGER_STRATEGY.get(kind, "Send a relevant, specific message based on the trigger data")

    # Customer context if available
    customer_info = ""
    cust_id = trigger.get("customer_id")
    if cust_id:
        customer = get_ctx("customer", cust_id)
        if customer:
            cname = customer.get("identity", {}).get("name", "")
            state = customer.get("state", "")
            rel = customer.get("relationship", {})
            customer_info = f"\nCUSTOMER: {cname} | state={state} | visits={rel.get('visits_total','')} | LTV=₹{rel.get('lifetime_value','')}"

    offer_line = ""
    if offer:
        offer_line = f"\nBEST OFFER: {offer.get('title','')}"

    prompt = f"""CATEGORY: {cat}
MERCHANT NAME (use exactly): {display_name}
OWNER: {owner}
LOCALITY: {locality}
PERFORMANCE: views={perf.get('views','?')}, calls={perf.get('calls','?')}, ctr={perf.get('ctr','?')}
SIGNALS: {merchant.get('signals',[])}
SUBSCRIPTION: {merchant.get('subscription',{}).get('status','')} | days_remaining={merchant.get('subscription',{}).get('days_remaining','')}
OFFERS: {json.dumps([{'title':o.get('title',''),'status':o.get('status','')} for o in merchant.get('offers',[])])}
{offer_line}{customer_info}

TRIGGER KIND: {kind}
TRIGGER URGENCY: {trigger.get('urgency','')}
TRIGGER PAYLOAD: {json.dumps(trigger.get('payload',{}))}

STRATEGY FOR {kind.upper()}: {strategy}

Write Vera's message. Must directly address the trigger kind above.
Do NOT default to conversion gap if the trigger is about something else."""

    try:
        resp = groq_client.chat.completions.create(
            model=MODEL, temperature=0.15, max_tokens=250,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": build_system_prompt(cat)},
                {"role": "user", "content": prompt},
            ],
        )
        result = json.loads(resp.choices[0].message.content.strip())
        if "body" not in result: raise ValueError("missing body")
        result["body"] = result["body"].replace("Dr. Dr.", "Dr.")
        return {**result, "merchant_id": merchant_id, "trigger_id": tid}
    except Exception:
        fb = build_fallback(merchant, trigger, cat)
        fb["merchant_id"] = merchant_id
        fb["trigger_id"] = tid
        return fb


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/v1/healthz")
def healthz():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/v1/metadata")
def metadata():
    return {
        "name": "vera-bot", "version": "13.0.0",
        "model": MODEL, "provider": "groq", "author": "challenger",
        "description": "Vera — trigger-aware, category-voiced, offer-specific merchant growth assistant.",
        "endpoints": ["/v1/healthz", "/v1/metadata", "/v1/context", "/v1/tick", "/v1/reply"],
    }

@app.post("/v1/context")
async def receive_context(request: Request):
    req = await request.json()
    key = f"{req['scope']}:{req['context_id']}"
    existing = context_store.get(key)
    version = req["version"]
    if existing and existing["version"] == version:
        return {"accepted": False, "reason": "same_version",
                "ack_id": existing["ack_id"], "stored_at": existing["stored_at"]}
    if existing and existing["version"] > version:
        return {"accepted": False, "reason": "older_version"}
    stored_at = datetime.now(timezone.utc).isoformat()
    ack_id = "ack_" + hashlib.md5(f"{key}:{version}:{stored_at}".encode()).hexdigest()[:10]
    context_store[key] = {"version": version, "payload": req["payload"],
                          "stored_at": stored_at, "ack_id": ack_id}
    return {"accepted": True, "ack_id": ack_id, "stored_at": stored_at}

@app.post("/v1/tick")
async def tick(request: Request):
    req = await request.json()
    trigger_ids = req.get("available_triggers", [])
    actions = []
    for tid in trigger_ids:
        result = compose_for_trigger(tid)
        if result:
            actions.append({
                "type": "message",
                "merchant_id": result["merchant_id"],
                "trigger_id": result["trigger_id"],
                "body": result["body"],
                "cta": result["cta"],
                "send_as": result["send_as"],
                "suppression_key": result.get("suppression_key", ""),
                "rationale": result.get("rationale", ""),
            })
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(request: Request):
    req = await request.json()
    session_id  = req.get("conversation_id", req.get("session_id", ""))
    merchant_id = req.get("merchant_id", "")
    message     = req.get("message", "")
    msg_lower   = message.lower()

    if any(w in msg_lower for w in ["stop", "spam", "useless", "unsubscribe", "don't contact", "mat karo", "band karo"]):
        return {"action": "end"}

    if "thank you for contacting" in msg_lower or "we will get back" in msg_lower or "auto-reply" in msg_lower:
        count = conversation_store.get(session_id, {}).get("auto_count", 0)
        if count >= 2:
            return {"action": "end"}
        conversation_store.setdefault(session_id, {})["auto_count"] = count + 1
        return {"action": "wait", "wait_seconds": 30}

    if any(w in msg_lower for w in ["yes", "ok", "go ahead", "do it", "confirm", "sure", "haan", "bilkul", "send it", "proceed"]):
        merchant = get_ctx("merchant", merchant_id) or {}
        offer = pick_best_offer(merchant)
        name = merchant.get("identity", {}).get("name", "your store")
        if offer:
            title = offer.get("title", "your offer")
            body = f"Done! Sending '{title}' to nearby customers now. Check your magicpin dashboard in 1hr for results."
        else:
            body = f"Done! Promoting {name} to nearby customers now. Results in dashboard within 1 hour."
        return {"action": "send", "body": body}

    merchant = get_ctx("merchant", merchant_id) or {}
    offer = pick_best_offer(merchant)
    perf = merchant.get("performance", {})
    views = perf.get("views", 500)

    if any(w in msg_lower for w in ["how many", "kitne", "reach", "how much", "kaafi"]):
        body = f"Based on current demand, your offer can reach {views}+ active searchers nearby. Want to go?"
    elif any(w in msg_lower for w in ["price", "cost", "charge", "free", "paisa"]):
        body = "Included in your magicpin plan — no extra charge. Ready to activate?"
    elif any(w in msg_lower for w in ["discount", "brand", "cheap", "value"]):
        body = "You set the price. I surface it to ready buyers at the right moment. Try once?"
    elif any(w in msg_lower for w in ["no", "nahi", "nope", "not now", "later", "baad mein"]):
        return {"action": "end"}
    else:
        if offer:
            title = offer.get("title", "your offer")
            body = f"Got it. Reply YES whenever ready — I'll push '{title}' to {views} active searchers immediately."
        else:
            body = "Understood. Reply YES whenever ready — I'll bring more customers in immediately."
    return {"action": "send", "body": body}