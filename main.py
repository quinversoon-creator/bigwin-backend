import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import random

FIREBASE_KEY_PATH = os.environ.get("FIREBASE_KEY_PATH") or "firebase_key.json"
if not os.path.exists(FIREBASE_KEY_PATH):
    raise Exception(f"Firebase key not found at {FIREBASE_KEY_PATH}. Asegura que el archivo exista en el servidor.")

cred = credentials.Certificate(FIREBASE_KEY_PATH)
try:
    firebase_admin.initialize_app(cred)
except ValueError:
    pass
db = firestore.client()
USERS_COLL = "users"

app = FastAPI(title="BIG WIN API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def iso_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def user_doc_ref(uid):
    return db.collection(USERS_COLL).document(str(uid))

def ensure_user(uid, name="Unknown"):
    ref = user_doc_ref(uid)
    snap = ref.get()
    if not snap.exists:
        data = {
            "name": name,
            "stars": 0,
            "language": "es",
            "referred_by": None,
            "referrals": [],
            "history": [],
            "games": {"dice": 0, "darts":0, "bowling":0, "slots":0},
            "games_total": 0,
            "joined": iso_now()
        }
        ref.set(data)
        return data
    return snap.to_dict() or {}

class UserIdBody(BaseModel):
    user_id: str = None

@app.get("/user/profile")
def get_profile(user_id: str = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id (query param).")
    uid = str(user_id)
    data = ensure_user(uid)
    data["id"] = uid
    data["ref_link"] = f"https://t.me/STARSBIGWIN_BOT?start={uid}"
    return data

@app.post("/user/bonus")
def claim_bonus(body: UserIdBody):
    if not body.user_id:
        raise HTTPException(status_code=400, detail="Missing user_id in body.")
    uid = str(body.user_id)
    ref = user_doc_ref(uid)
    snap = ref.get()
    if not snap.exists:
        ensure_user(uid)
        snap = ref.get()
    data = snap.to_dict() or {}
    last = data.get("last_bonus_ts")
    now = datetime.utcnow()
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            delta = (now - last_dt).total_seconds()
            if delta < 86400:
                hours = int((86400 - delta) // 3600) + 1
                return {"ok": False, "message": f"Ya reclamaste hoy. Vuelve en {hours} horas."}
        except Exception:
            pass
    amount = random.randint(5, 15)
    ref.update({"stars": firestore.Increment(amount), "last_bonus_ts": now.isoformat(), "history": firestore.ArrayUnion([{"ts": now.isoformat(), "game":"bonus", "prize": amount}])})
    return {"ok": True, "amount": amount, "message": f"Reclamaste {amount}⭐"}

@app.get("/ranking")
def get_ranking(limit: int = 50):
    users_q = db.collection(USERS_COLL).order_by("stars", direction=firestore.Query.DESCENDING).limit(limit).stream()
    top = []
    for u in users_q:
        d = u.to_dict() or {}
        top.append({"id": u.id, "name": d.get("name","Anon"), "stars": d.get("stars",0)})
    return {"top": top}

@app.get("/user/history")
def get_history(user_id: str = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    snap = user_doc_ref(user_id).get()
    if not snap.exists:
        return {"history": []}
    data = snap.to_dict() or {}
    return {"history": data.get("history", [])}

@app.get("/user/referrals")
def get_referrals(user_id: str = None):
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    snap = user_doc_ref(user_id).get()
    if not snap.exists:
        return {"referrals": []}
    data = snap.to_dict() or {}
    return {"referrals": data.get("referrals", []), "ref_link": f"https://t.me/STARSBIGWIN_BOT?start={user_id}"}
