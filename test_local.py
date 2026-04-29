"""Quick test — run while uvicorn is running locally."""
import json, requests

BASE = "http://localhost:8000"

def show(label, r):
    mark = "✅" if r.status_code == 200 else "❌"
    print(f"{mark} {label} [{r.status_code}]")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False), "\n")

show("healthz",   requests.get(f"{BASE}/v1/healthz"))
show("metadata",  requests.get(f"{BASE}/v1/metadata"))

show("context merchant", requests.post(f"{BASE}/v1/context", json={
    "scope": "merchant", "context_id": "m_001_drmeera", "version": 1,
    "payload": {
        "identity": {"name": "Dr. Meera Dental Clinic", "category": "dentist", "locality": "Koramangala, Bengaluru"},
        "performance": {"views_7d": 190, "bookings_7d": 3, "avg_rating": 4.6},
        "offers": [{"name": "Dental Check Up", "price": 299, "original_price": 599}]
    },
    "delivered_at": "2026-04-29T10:00:00Z"
}))

show("context trigger", requests.post(f"{BASE}/v1/context", json={
    "scope": "trigger", "context_id": "t_spike_dental", "version": 1,
    "payload": {
        "type": "search_spike",
        "signal": "190 people in Koramangala searched 'Dental Check Up' in last 24h",
        "urgency": "high"
    },
    "delivered_at": "2026-04-29T10:00:00Z"
}))

show("tick", requests.post(f"{BASE}/v1/tick", json={
    "session_id": "sess_001", "merchant_id": "m_001_drmeera", "trigger_id": "t_spike_dental"
}))

show("reply", requests.post(f"{BASE}/v1/reply", json={
    "session_id": "sess_001", "merchant_id": "m_001_drmeera",
    "message": "Yes! How many people will see the offer?"
}))
