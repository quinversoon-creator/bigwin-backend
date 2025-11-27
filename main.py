import os
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
import random
import hashlib
import hmac

# ============================================================
#  FIREBASE usando FIREBASE_KEY_JSON (variable de entorno)
# ============================================================

firebase_json = os.environ.get("FIREBASE_KEY_JSON")
if not firebase_json:
    raise Exception("ERROR: Debes configurar FIREBASE_KEY_JSON en Render.")

cred = credentials.Certificate(json.loads(firebase_json))

try:
    firebase_admin.initialize_app(cred)
except ValueError:
    pass

db = firestore.client()
USERS_COLL = "users"

# ============================================================
#  FASTAPI APP
# ============================================================

app = FastAPI(title="BIG WIN API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
#  HELPERS
# ============================================================

def iso_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def user_ref(uid):
    return db.collection(USERS_COLL).document(str(uid))

def ensure_user(uid, name="Usuario"):
    doc = user_ref(uid).get()
    if not doc.exists():
        data = {
            "name": name,
            "stars": 0,
            "language": "es",
            "referred_by": None,
            "referrals": [],
            "history": [],
            "games": {"dice":0, "darts":0, "bowling":0, "slots":0},
            "games_total": 0,
            "joined": iso_now()
        }
        user_ref(uid).set(data)
        return data
    return doc.to_dict() or {}

# ============================================================
#  MODELOS
# ============================================================

class UserIdBody(BaseModel):
    user_id: str


class GameRequest(BaseModel):
    user_id: str
    bet: int


# ============================================================
#  ENDPOINT: PERFIL
# ============================================================

@app.get("/user/profile")
def profile(user_id: str = None):
    if not user_id:
        raise HTTPException(400, "user_id faltante")
    uid = str(user_id)
    data = ensure_user(uid)
    data["id"] = uid
    data["ref_link"] = f"https://t.me/STARSBIGWIN_BOT?start={uid}"
    return data


# ============================================================
#  ENDPOINT: BONUS DIARIO
# ============================================================

@app.post("/user/bonus")
def bonus(body: UserIdBody):
    uid = str(body.user_id)
    ref = user_ref(uid)
    snap = ref.get()

    if not snap.exists():
        ensure_user(uid)

    data = snap.to_dict()
    last = data.get("last_bonus_ts")
    now = datetime.utcnow()

    if last:
        last_dt = datetime.fromisoformat(last)
        if (now - last_dt).total_seconds() < 86400:
            remaining = 86400 - (now - last_dt).total_seconds()
            hours = int(remaining // 3600) + 1
            return {"ok": False, "message": f"Vuelve en {hours} horas."}

    amount = random.randint(5, 15)

    ref.update({
        "stars": firestore.Increment(amount),
        "last_bonus_ts": now.isoformat(),
        "history": firestore.ArrayUnion([
            {"ts": now.isoformat(), "game": "bonus", "prize": amount}
        ])
    })

    return {"ok": True, "amount": amount, "message": f"Ganaste {amount}⭐"}


# ============================================================
#  JUEGOS (dados, dardos, boliche, slots)
# ============================================================

def game_play(uid, game_name, bet):
    ref = user_ref(uid)
    snap = ref.get()

    if not snap.exists():
        ensure_user(uid)
        snap = ref.get()

    data = snap.to_dict()

    if bet <= 0:
        raise HTTPException(400, "Apuesta inválida")

    if data["stars"] < bet:
        raise HTTPException(400, "No tienes suficientes estrellas")

    win = random.random() < 0.45
    prize = bet * (2 if win else 0)

    ref.update({
        "stars": firestore.Increment(prize - bet),
        "games_total": firestore.Increment(1),
        f"games.{game_name}": firestore.Increment(1),
        "history": firestore.ArrayUnion([
            {"ts": iso_now(), "game": game_name, "bet": bet, "win": prize}
        ])
    })

    return {
        "ok": True,
        "win": win,
        "prize": prize,
        "stars_after": data["stars"] + (prize - bet)
    }


@app.post("/game/dice")
def game_dice(req: GameRequest):
    return game_play(req.user_id, "dice", req.bet)

@app.post("/game/darts")
def game_darts(req: GameRequest):
    return game_play(req.user_id, "darts", req.bet)

@app.post("/game/bowling")
def game_bowling(req: GameRequest):
    return game_play(req.user_id, "bowling", req.bet)

@app.post("/game/slots")
def game_slots(req: GameRequest):
    return game_play(req.user_id, "slots", req.bet)


# ============================================================
#  RANKING / HISTORIAL / REFERIDOS
# ============================================================

@app.get("/ranking")
def ranking(limit: int = 50):
    users = db.collection(USERS_COLL).order_by("stars", direction=firestore.Query.DESCENDING).limit(limit).stream()
    out = [{"id": u.id, "name": u.to_dict().get("name"), "stars": u.to_dict().get("stars")} for u in users]
    return {"top": out}

@app.get("/user/history")
def history(user_id: str):
    snap = user_ref(user_id).get()
    if not snap.exists():
        return {"history": []}
    return {"history": snap.to_dict().get("history", [])}

@app.get("/user/referrals")
def referrals(user_id: str):
    snap = user_ref(user_id).get()
    if not snap.exists():
        return {"referrals": []}
    d = snap.to_dict()
    return {
        "referrals": d.get("referrals", []),
        "ref_link": f"https://t.me/STARSBIGWIN_BOT?start={user_id}"
    }


# ============================================================
#  SIMPLE WEBHOOK (Placeholder)
# ============================================================

@app.post("/webhook")
async def webhook():
    return {"ok": True}
