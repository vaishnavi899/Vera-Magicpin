# Vera Bot — magicpin AI Challenge

## Overview
This project implements a **decision-driven AI assistant (Vera)** that helps merchants take timely actions based on real business signals such as demand spikes, performance dips, renewals, and customer behavior.

The system is designed to:
- Generate **high-quality, trigger-aware messages**
- Maintain **category-specific tone and compliance**
- Drive **merchant actions with clear CTAs**

---

## Live Bot URL
https://vera-magicpin.onrender.com

---

## Key Features

### 1. Trigger-Aware Messaging
Each message is generated based on a specific trigger:
- Performance dip
- Festival demand
- Renewal reminders
- Competitor alerts
- Customer winback

Messages are **not generic** they directly respond to the trigger context.

---

### 2. Category-Specific Voice
The bot adapts tone based on business type:

| Category | Tone |
|----------|------|
| Dentists | Clinical, professional |
| Salons | Warm, practical |
| Restaurants | Fast-paced, business-focused |
| Gyms | Energetic |
| Pharmacies | Trust-focused |

This ensures **high category fit score**.

---

### 3. Strong Personalization
Messages include:
- Merchant name
- Locality
- Performance metrics (views, calls, CTR)
- Active offers with pricing

This improves **specificity + merchant relevance**.

---

### 4. LLM + Fallback Architecture
- Primary: Groq (llama-3.3-70b-versatile)
- Fallback: Deterministic rule-based generator

This ensures:
- Reliability (no failures)
- Consistent output under load

---

### 5. Parallel Processing (Critical Optimization)
The `/v1/tick` endpoint processes triggers **in parallel** using thread pools.

Why this matters:
- Avoids timeout failures
- Handles multiple triggers efficiently
- Improves judge performance

---

### 6. Smart Conversation Handling
Reply logic includes:
- Auto-reply detection → waits or ends
- Intent detection → executes actions
- Hostile handling → exits safely

---

## API Endpoints

- `/v1/healthz` → Health check
- `/v1/metadata` → Bot details
- `/v1/context` → Receive dataset context
- `/v1/tick` → Generate actions
- `/v1/reply` → Handle merchant replies

---

## Model Choice

**Groq — llama-3.3-70b-versatile**

Reason:
- Fast inference
- Strong structured output
- Good balance of quality + latency

---

## Design Tradeoffs

| Decision | Tradeoff |
|---------|---------|
| LLM + fallback | Slight complexity ↑, reliability ↑ |
| Parallel execution | More threads, but avoids timeouts |
| Strict prompts | Less creativity, more scoring consistency |

---

## How It Maximizes Score

- High specificity → real numbers, offers, locality
- Strong trigger relevance → no generic messaging
- Category fit → controlled tone system
- Engagement → clear CTA (YES/NO)
- Reliability → no failures under judge load

---

## Tech Stack

- FastAPI
- Groq API
- Python
- Async + ThreadPoolExecutor

---

## Final Note
This bot is designed to balance:
- Intelligence (LLM)
- Reliability (fallbacks)
- Performance (parallel execution)

Result: **Consistent high-quality outputs under evaluation conditions.**