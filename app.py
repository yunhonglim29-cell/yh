"""CITY HUNT: a single-event, server-authoritative multiplayer treasure hunt.

SQLite transactions serialize scored actions. No answer keys or future mission
prompts are sent to player clients. Photos are re-encoded and served privately.
Run with `python run.py`; see README.md for HTTPS/persistent-volume deployment.
"""
from __future__ import annotations
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata
from urllib.parse import urlparse
import uuid
import warnings
import zipfile
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
import qrcode
from seed import make_missions

ROOT = Path(__file__).resolve().parent
MAX_BODY = 12 * 1024 * 1024
MAX_PIXELS = 26_000_000
TYPES = {"text", "choice", "multi", "number", "photo", "observation", "matching", "ordering", "puzzle", "team"}
COLOURS = ["#ffc86a", "#6edbcb", "#a6b3ff", "#ff9b99", "#b7dc82", "#77c7ef", "#dab0f7", "#f0b7cb"]


def now() -> int:
    return int(time.time() * 1000)


def packed(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def digest_password(value: str) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${hashed.hex()}"


def check_password(value: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$")
        actual = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def text(value: Any, limit: int = 3000, minimum: int = 0) -> str:
    if not isinstance(value, str):
        raise HTTPException(400, "Expected text.")
    value = value.strip()
    if len(value) < minimum or len(value) > limit:
        raise HTTPException(400, f"Please enter between {minimum} and {limit} characters.")
    return value


def integer(value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise HTTPException(400, "Expected a whole number.")
    try:
        n = int(value)
        if isinstance(value, float) and value != n:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "Expected a whole number.")
    if not lo <= n <= hi:
        raise HTTPException(400, f"Number must be between {lo} and {hi}.")
    return n


def normalized(value: Any, sensitive: bool = False) -> str:
    s = unicodedata.normalize("NFKC", str(value)).strip()
    if not sensitive:
        s = s.casefold()
    return " ".join("".join(c if c.isalnum() or c.isspace() else " " for c in s).split())


def is_correct(stage: dict, answer: Any) -> bool:
    kind = stage["type"]
    if kind in {"text", "puzzle", "observation"}:
        sensitive = stage.get("caseSensitive", False)
        a = normalized(answer, sensitive)
        accepted = [normalized(x, sensitive) for x in stage.get("accepted", [])]
        if a in accepted:
            return True
        words = [normalized(x, sensitive) for x in stage.get("keywords", []) if normalized(x, sensitive)]
        if not words:
            return False
        hits = [(" " + x + " ") in (" " + a + " ") for x in words]
        return all(hits) if stage.get("matchMode") == "all_keywords" else any(hits)
    if kind == "number":
        try:
            n = float(answer)
            if not math.isfinite(n):
                return False
            if "minAnswer" in stage and "maxAnswer" in stage:
                return float(stage["minAnswer"]) <= n <= float(stage["maxAnswer"])
            return abs(n - float(stage["correct"])) <= float(stage.get("tolerance", 0))
        except (ValueError, TypeError, KeyError):
            return False
    if kind == "choice":
        return answer == stage.get("correct")
    if kind == "multi":
        return isinstance(answer, list) and len(answer) == len(set(answer)) and set(answer) == set(stage.get("correct", []))
    if kind == "matching":
        return isinstance(answer, dict) and answer == stage.get("correct")
    if kind == "ordering":
        return isinstance(answer, list) and answer == stage.get("correct")
    return False


def validate_answer(stage: dict, answer: Any) -> Any:
    k = stage["type"]
    if k in {"text", "observation", "puzzle", "number"}:
        return text(str(answer) if isinstance(answer, (int, float)) else answer, 3000, 1)
    if k == "choice":
        if answer not in stage.get("options", []):
            raise HTTPException(400, "Choose one of the listed options.")
    elif k == "multi":
        if not isinstance(answer, list) or not answer or any(x not in stage.get("options", []) for x in answer) or len(answer) != len(set(answer)):
            raise HTTPException(400, "Select one or more listed options.")
    elif k == "matching":
        ids = {x["id"] for x in stage.get("items", [])}
        if not isinstance(answer, dict) or set(answer) != ids or any(x not in stage.get("categories", []) for x in answer.values()):
            raise HTTPException(400, "Match every item to a category.")
    elif k == "ordering":
        ids = {x["id"] for x in stage.get("items", [])}
        if not isinstance(answer, list) or len(answer) != len(ids) or any(not isinstance(x, str) for x in answer) or set(answer) != ids:
            raise HTTPException(400, "Arrange all the items.")
    else:
        raise HTTPException(400, "Upload a photo for this challenge.")
    return answer


def validate_mission(raw: dict, mission_id: int) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(400, "Mission must be an object.")
    doc = {"id": mission_id, "title": text(raw.get("title"), 100, 1),
           "subtitle": text(raw.get("subtitle", ""), 200), "clue": text(raw.get("clue"), 5000, 1),
           "verified": bool(raw.get("verified", False)), "hints": [], "stages": []}
    hints = raw.get("hints", [])
    if not isinstance(hints, list) or len(hints) > 3:
        raise HTTPException(400, "Use up to three hints.")
    for hint in hints:
        if not isinstance(hint, dict):
            raise HTTPException(400, "Each hint must be an object.")
        doc["hints"].append({"text": text(hint.get("text"), 500, 1), "cost": integer(hint.get("cost", 0), 0, 50),
                             "delaySeconds": integer(hint.get("delaySeconds", 0), 0, 7200)})
    stages = raw.get("stages", [])
    if not isinstance(stages, list) or not 1 <= len(stages) <= 12:
        raise HTTPException(400, "Add between 1 and 12 stages.")
    used = set()
    for original in stages:
        if not isinstance(original, dict):
            raise HTTPException(400, "Each stage must be an object.")
        s = dict(original)
        sid = text(s.get("id"), 48, 1)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", sid) or sid in used:
            raise HTTPException(400, "Each stage needs a unique alphanumeric ID.")
        used.add(sid)
        if s.get("type") not in TYPES:
            raise HTTPException(400, "Unknown challenge type.")
        s["id"] = sid
        s["label"] = text(s.get("label", "Challenge"), 80, 1)
        s["prompt"] = text(s.get("prompt"), 5000, 1)
        s["points"] = integer(s.get("points", 10), 0, 100)
        s["attempts"] = integer(s.get("attempts", 2), 1, 10)
        s["grading"] = s.get("grading", "auto")
        if s["grading"] not in {"auto", "manual", "photo"}:
            raise HTTPException(400, "Invalid grading mode.")
        if s["type"] in {"photo", "team"}:
            s["grading"] = "manual" if s["grading"] == "manual" else "photo"
        elif s["grading"] == "photo":
            raise HTTPException(400, "Photo grading requires a photo or team challenge.")
        if s["type"] in {"choice", "multi"}:
            opts = s.get("options")
            if not isinstance(opts, list) or not 2 <= len(opts) <= 12 or any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in opts) or len(set(opts)) != len(opts):
                raise HTTPException(400, "Provide 2 to 12 distinct answer options.")
            if s["grading"] == "auto":
                correct = s.get("correct")
                if (s["type"] == "choice" and correct not in opts) or (s["type"] == "multi" and (not isinstance(correct, list) or not correct or any(x not in opts for x in correct))):
                    raise HTTPException(400, "Correct answers must be among the options.")
        if s["type"] in {"matching", "ordering"}:
            items = s.get("items", [])
            if not isinstance(items, list) or not 2 <= len(items) <= 10 or any(not isinstance(x, dict) or not isinstance(x.get("id"), str) or not isinstance(x.get("text"), str) for x in items):
                raise HTTPException(400, "Provide 2 to 10 items with id and text.")
            ids = [x["id"] for x in items]
            if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", x) for x in ids):
                raise HTTPException(400, "Item IDs must be unique and alphanumeric.")
            if s["type"] == "matching":
                cats = s.get("categories", [])
                if not isinstance(cats, list) or not cats or any(not isinstance(x, str) or not x or len(x) > 200 for x in cats):
                    raise HTTPException(400, "Provide matching categories.")
                if s["grading"] == "auto" and (not isinstance(s.get("correct"), dict) or set(s["correct"]) != set(ids) or any(x not in cats for x in s["correct"].values())):
                    raise HTTPException(400, "Provide the correct category for every item.")
            elif s["grading"] == "auto" and (not isinstance(s.get("correct"), list) or len(s["correct"]) != len(ids) or set(s["correct"]) != set(ids)):
                raise HTTPException(400, "Correct order must contain every item exactly once.")
        if s["type"] in {"text", "puzzle", "observation"} and s["grading"] == "auto":
            for key in ("accepted", "keywords"):
                if not isinstance(s.get(key, []), list) or any(not isinstance(x, str) or len(x) > 500 for x in s.get(key, [])):
                    raise HTTPException(400, "Accepted answers and keywords must be lists of text.")
            if not s.get("accepted") and not s.get("keywords"):
                raise HTTPException(400, "Add accepted answers or choose manual grading.")
        if s["type"] == "number" and s["grading"] == "auto":
            try:
                vals = [float(s["minAnswer"]), float(s["maxAnswer"])] if "minAnswer" in s else [float(s["correct"]), float(s.get("tolerance", 0))]
                if not all(math.isfinite(x) for x in vals) or ("minAnswer" in s and vals[0] > vals[1]) or ("minAnswer" not in s and vals[1] < 0):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise HTTPException(400, "Provide a valid numeric answer and non-negative tolerance, or a valid range.")
        doc["stages"].append(s)
    return doc


class Store:
    def __init__(self, directory: Path, production: bool = False, password: str | None = None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.uploads = directory / "uploads"
        self.uploads.mkdir(exist_ok=True)
        self.backups = directory / "backups"
        self.backups.mkdir(exist_ok=True)
        self.path = directory / "city-hunt.sqlite3"
        with self.db(write=True) as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS missions (id INTEGER PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS teams (id INTEGER PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, team INTEGER NOT NULL, name TEXT NOT NULL, joined INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, team INTEGER, mission INTEGER, stage TEXT, generation INTEGER DEFAULT 0, active INTEGER DEFAULT 1, doc TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_submission ON submissions(team,mission,stage,generation);
                CREATE TABLE IF NOT EXISTS attempts (request_id TEXT PRIMARY KEY, team INTEGER, mission INTEGER, stage TEXT, generation INTEGER, answer TEXT, correct INTEGER, at INTEGER);
                CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, action_key TEXT UNIQUE NOT NULL, team INTEGER, mission INTEGER, stage TEXT, category TEXT, points INTEGER, reason TEXT, actor TEXT, at INTEGER);
                CREATE INDEX IF NOT EXISTS ledger_team ON ledger(team);
                CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, team INTEGER, actor TEXT, message TEXT);
                CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, count INTEGER, until_time INTEGER);
            ''')
            if not c.execute("SELECT 1 FROM config").fetchone():
                if production and (not password or len(password) < 12):
                    raise RuntimeError("Set ADMIN_PASSWORD to at least 12 characters before first production startup.")
                password = password or secrets.token_urlsafe(15)
                if not production:
                    print(f"\nCITY HUNT FIRST-RUN ORGANISER PASSWORD: {password}\nSave this password. Open /admin to sign in.\n", flush=True)
                cfg = {"name": "CITY HUNT", "subtitle": "THE URA CHALLENGE", "venue": "Singapore City Gallery",
                       "eventId": uuid.uuid4().hex, "status": "lobby", "requireCodes": True,
                       "leaderboard": True, "leaderboardLocked": False, "lockAt": 7,
                       "resultsRevealed": False, "timerEnabled": False, "durationMinutes": 90,
                       "startedAt": None, "deadlineAt": None, "pausedAt": None, "pauseHistory": [],
                       "photoMode": "immediate", "helpContact": "Please contact your event organiser.",
                       "rehearsal": True, "announcements": [], "revision": 1,
                       "adminHash": digest_password(password)}
                c.execute("INSERT INTO config VALUES (1,?)", (packed(cfg),))
                for i in range(1, 9):
                    code = secrets.token_hex(3).upper() if production else f"CITY0{i}"
                    team = {"id": i, "name": f"Team {i}", "colour": COLOURS[i-1], "code": code,
                            "codeHash": digest_password(code), "index": 0, "progress": {}, "startedAt": None,
                            "completedAt": None, "paused": False, "pauseHistory": []}
                    c.execute("INSERT INTO teams VALUES (?,?)", (i, packed(team)))
                for mission in make_missions():
                    c.execute("INSERT INTO missions VALUES (?,?)", (mission["id"], packed(mission)))
            elif password:
                # An environment password is an explicit credential configuration, including rotation.
                cfg = self.config(c)
                if not check_password(password, cfg["adminHash"]):
                    if len(password) < 12:
                        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters.")
                    cfg["adminHash"] = digest_password(password)
                    self.put_config(c, cfg)

    @contextmanager
    def db(self, write: bool = False):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=20000")
        try:
            c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def config(self, c):
        return json.loads(c.execute("SELECT doc FROM config WHERE id=1").fetchone()[0])

    def put_config(self, c, cfg):
        c.execute("UPDATE config SET doc=? WHERE id=1", (packed(cfg),))

    def team(self, c, tid):
        row = c.execute("SELECT doc FROM teams WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404, "Team not found.")
        return json.loads(row[0])

    def put_team(self, c, team):
        c.execute("UPDATE teams SET doc=? WHERE id=?", (packed(team), team["id"]))

    def mission(self, c, mid):
        row = c.execute("SELECT doc FROM missions WHERE id=?", (mid,)).fetchone()
        if not row:
            raise HTTPException(404, "Mission not found.")
        return json.loads(row[0])

    @staticmethod
    def route(team):
        return [(team["id"] - 1 + n) % 8 + 1 for n in range(8)] + [9]

    def current(self, c, team):
        if team["index"] >= 9:
            return None, None
        mission = self.mission(c, self.route(team)[team["index"]])
        progress = team["progress"].setdefault(str(mission["id"]), {"startedAt": None, "completedAt": None, "stageIndex": 0, "hints": [], "generation": 0})
        return mission, progress

    @staticmethod
    def log(c, actor, message, tid=None):
        c.execute("INSERT INTO logs(at,team,actor,message) VALUES (?,?,?,?)", (now(), tid, actor, message))

    @staticmethod
    def award(c, key, tid, points, reason, actor, category="mission", mid=None, sid=None):
        c.execute("INSERT OR IGNORE INTO ledger VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (uuid.uuid4().hex, key, tid, mid, sid, category, points, reason, actor, now()))

    def bump(self, c):
        cfg = self.config(c)
        cfg["revision"] += 1
        self.put_config(c, cfg)

    @staticmethod
    def admin(session):
        return session.get("adminAt", 0) > now() - 8 * 60 * 60 * 1000

    def require_admin(self, session):
        if not self.admin(session):
            raise HTTPException(401, "Sign in to the organiser dashboard.")

    def player(self, c, session):
        p = c.execute("SELECT * FROM players WHERE id=?", (session.get("playerId", ""),)).fetchone()
        if not p:
            raise HTTPException(401, "Join a team to continue.")
        return dict(p)

    @staticmethod
    def live(cfg, team):
        if cfg["status"] != "live":
            raise HTTPException(409, "The game is not live. Please follow the organiser's instructions.")
        if team["paused"]:
            raise HTTPException(409, "Your team is paused. Please speak to the organiser.")
        if cfg.get("timerEnabled") and cfg.get("deadlineAt") and now() > cfg["deadlineAt"]:
            raise HTTPException(409, "Time is up. Your progress is saved; please return to the organiser.")

    @staticmethod
    def throttle(c, key, maximum, seconds):
        row = c.execute("SELECT * FROM limits WHERE key=?", (key,)).fetchone()
        if row and row["until_time"] > now() and row["count"] >= maximum:
            raise HTTPException(429, "Too many attempts. Please try again in a few minutes.")
        if not row or row["until_time"] <= now():
            c.execute("INSERT OR REPLACE INTO limits VALUES (?,?,?)", (key, 1, now() + seconds * 1000))
        else:
            c.execute("UPDATE limits SET count=count+1 WHERE key=?", (key,))

    def public_config(self, cfg):
        return {k: v for k, v in cfg.items() if k != "adminHash" and k != "announcements"}

    def bootstrap(self, session):
        with self.db() as c:
            cfg = self.config(c)
            return {"config": self.public_config(cfg), "teams": [{"id": t["id"], "name": t["name"], "colour": t["colour"]} for t in (json.loads(r[0]) for r in c.execute("SELECT doc FROM teams ORDER BY id"))],
                    "player": bool(c.execute("SELECT 1 FROM players WHERE id=?", (session.get("playerId", ""),)).fetchone()),
                    "admin": self.admin(session), "csrf": session["csrf"], "serverNow": now()}

    def leaderboard(self, c, cfg, admin=False):
        teams = [json.loads(r[0]) for r in c.execute("SELECT doc FROM teams")]
        hidden = not cfg["leaderboard"] or cfg["leaderboardLocked"] or (cfg.get("lockAt", 0) and any(t["index"] >= cfg["lockAt"] for t in teams))
        if cfg["resultsRevealed"]:
            hidden = False
        if hidden and not admin:
            return {"hidden": True, "rows": []}
        rows = []
        for t in teams:
            score = c.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE team=?", (t["id"],)).fetchone()[0]
            rows.append({"id": t["id"], "name": t["name"], "colour": t["colour"], "score": score,
                         "completed": min(t["index"], 8), "finishedAt": t["completedAt"]})
        rows.sort(key=lambda t: (-t["score"], t["finishedAt"] or math.inf, t["id"]))
        previous = None
        rank = 0
        for index, r in enumerate(rows, 1):
            key = (r["score"], r["finishedAt"])
            if key != previous:
                rank = index
            r["rank"] = rank
            previous = key
        return {"hidden": bool(hidden), "rows": rows}

    def state(self, session, admin=False):
        with self.db() as c:
            cfg = self.config(c)
            if admin:
                self.require_admin(session)
                return self.admin_state(c, cfg)
            p = self.player(c, session)
            t = self.team(c, p["team"])
            m, progress = self.current(c, t)
            ledger = [dict(r) for r in c.execute("SELECT * FROM ledger WHERE team=? ORDER BY at DESC", (t["id"],))]
            submissions = [json.loads(r[0]) for r in c.execute("SELECT doc FROM submissions WHERE team=? AND active=1 ORDER BY rowid", (t["id"],))]
            score = sum(l["points"] for l in ledger)
            pending = sum(s["status"] == "pending" for s in submissions)
            score_parts = {cat: sum(l["points"] for l in ledger if l["category"] == cat) for cat in ["mission", "final", "bonus", "hint", "adjustment"]}
            current = None
            if m:
                current = {"id": m["id"], "title": m["title"], "subtitle": m["subtitle"], "started": bool(progress["startedAt"]),
                           "startedAt": progress["startedAt"], "stageIndex": progress["stageIndex"], "stageCount": len(m["stages"]),
                           "maxPoints": sum(s["points"] for s in m["stages"]), "final": m["id"] == 9,
                           "stageLabels": [{"label": s["label"], "points": s["points"]} for s in m["stages"]]}
                if progress["startedAt"]:
                    current["clue"] = m["clue"]
                    current["hints"] = [{"index": i, "cost": h["cost"], "delaySeconds": h.get("delaySeconds", 0),
                                         "unlocked": i in progress["hints"], "text": h["text"] if i in progress["hints"] else None}
                                        for i, h in enumerate(m["hints"])]
                    stage = m["stages"][progress["stageIndex"]]
                    # Explicit allow-list: answer keys NEVER appear in a player payload.
                    current["stage"] = {k: stage[k] for k in ["id", "label", "type", "prompt", "points", "attempts", "grading", "options", "items", "categories"] if k in stage}
                    used = c.execute("SELECT COUNT(*) FROM attempts WHERE team=? AND mission=? AND stage=? AND generation=?", (t["id"], m["id"], stage["id"], progress["generation"])).fetchone()[0]
                    current["stage"]["attemptsUsed"] = used
            teammates = [dict(r) for r in c.execute("SELECT id,name,joined FROM players WHERE team=? ORDER BY joined", (t["id"],))]
            public_t = {k: t[k] for k in ["id", "name", "colour", "index", "startedAt", "completedAt", "paused", "pauseHistory"]}
            public_t.update({"score": score, "completed": min(t["index"], 8), "finished": t["index"] >= 9, "pending": pending, "scoreParts": score_parts})
            completed = []
            for mid, pg in t["progress"].items():
                if pg.get("completedAt"):
                    mm = self.mission(c, int(mid))
                    completed.append({"id": int(mid), "title": mm["title"], "startedAt": pg["startedAt"], "completedAt": pg["completedAt"], "skipped": pg.get("skipped", False)})
            return {"config": self.public_config(cfg), "player": p, "team": public_t, "current": current,
                    "completedMissions": completed, "members": teammates, "leaderboard": self.leaderboard(c, cfg),
                    "submissions": submissions, "ledger": ledger, "serverNow": now(),
                    "announcements": [a for a in cfg["announcements"] if a.get("team") in (None, t["id"])][-8:]}

    def admin_state(self, c, cfg):
        teams = []
        for r in c.execute("SELECT doc FROM teams ORDER BY id"):
            t = json.loads(r[0])
            t.pop("codeHash", None)
            t["score"] = c.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE team=?", (t["id"],)).fetchone()[0]
            t["members"] = [dict(p) for p in c.execute("SELECT id,name,joined FROM players WHERE team=?", (t["id"],))]
            t["route"] = self.route(t)
            teams.append(t)
        return {"config": self.public_config(cfg), "teams": teams,
                "missions": [json.loads(r[0]) for r in c.execute("SELECT doc FROM missions ORDER BY id")],
                "submissions": [json.loads(r[0]) for r in c.execute("SELECT doc FROM submissions WHERE active=1 ORDER BY rowid DESC")],
                "ledger": [dict(r) for r in c.execute("SELECT * FROM ledger ORDER BY at DESC")],
                "logs": [dict(r) for r in c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 250")],
                "leaderboard": self.leaderboard(c, cfg, admin=True), "serverNow": now(), "announcements": cfg["announcements"][-20:]}

    def authenticate(self, action, data, session, ip):
        # Rate-limit attempts in their own committed transaction, including failed logins.
        with self.db(write=True) as c:
            self.throttle(c, f"{action}:{ip}", 20 if action == "admin/login" else 100, 300)
        with self.db(write=True) as c:
            cfg = self.config(c)
            if action == "admin/login":
                password = text(data.get("password", ""), 256, 1)
                if not check_password(password, cfg["adminHash"]):
                    raise HTTPException(401, "Incorrect organiser password.")
                session["adminAt"] = now()
                self.log(c, "Organiser", "Signed in to organiser dashboard")
            else:
                if cfg["status"] == "ended":
                    raise HTTPException(409, "This event has ended. Ask the organiser to reopen it for joining.")
                tid = integer(data.get("team"), 1, 8)
                t = self.team(c, tid)
                name = text(data.get("name"), 40, 1)
                code = text(data.get("code", ""), 64)
                if cfg["requireCodes"] and not check_password(code.upper(), t["codeHash"]):
                    raise HTTPException(403, "That team code is not correct. Check with your organiser.")
                pid = uuid.uuid4().hex
                c.execute("INSERT INTO players VALUES (?,?,?,?)", (pid, tid, name, now()))
                session["playerId"] = pid
                self.log(c, name, "Joined the team", tid)
            self.bump(c)
        return {"ok": True}

    def process_photo(self, image_data: Any) -> str:
        data = text(image_data, MAX_BODY, 1)
        if not data.startswith("data:image/") or ";base64," not in data:
            raise HTTPException(400, "Choose a JPEG, PNG or WebP photograph.")
        try:
            raw = base64.b64decode(data.split(",", 1)[1], validate=True)
            if len(raw) > 8 * 1024 * 1024:
                raise HTTPException(413, "Photo is too large. Choose an image under 8 MB.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as im:
                    if im.format not in {"JPEG", "PNG", "WEBP"} or im.width * im.height > MAX_PIXELS or min(im.size) < 32:
                        raise HTTPException(400, "Use a clear JPEG, PNG or WebP photo (at least 32 pixels per side).")
                    im.load()
                    photo = ImageOps.exif_transpose(im).convert("RGB")
                    photo.thumbnail((1600, 1600))
                    name = secrets.token_hex(20) + ".jpg"
                    # Re-encoding strips location/EXIF metadata and rejects disguised file payloads.
                    photo.save(self.uploads / name, "JPEG", quality=84, optimize=True)
                    return name
        except HTTPException:
            raise
        except (ValueError, binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise HTTPException(400, "This image could not be read. Retake it or choose a JPEG/PNG photo.")

    def act(self, action, data, session, ip):
        if action in {"join", "admin/login"}:
            return self.authenticate(action, data, session, ip)
        if action == "logout":
            session.pop("playerId", None)
            return {"ok": True}
        if action == "admin/logout":
            session.pop("adminAt", None)
            return {"ok": True}
        if action.startswith("admin/"):
            self.require_admin(session)
            if action in {"admin/reset", "admin/reset-team"}:
                expected = "RESET CITY HUNT" if action == "admin/reset" else "RESET TEAM"
                if data.get("confirmation") != expected:
                    raise HTTPException(400, f"Type {expected} to confirm.")
                with self.db() as c:
                    if self.config(c)["status"] == "live":
                        raise HTTPException(409, "Pause or end the event before resetting a team or the whole game.")
                self.backup()
            return self.admin_act(action, data)
        with self.db() as c:
            p = self.player(c, session)
            cfg = self.config(c)
            t = self.team(c, p["team"])
            self.live(cfg, t)
        filename = None
        if action == "photo":
            # Authenticate BEFORE decoding or writing any uploaded image.
            filename = self.process_photo(data.get("image"))
        try:
            with self.db(write=True) as c:
                p = self.player(c, session)
                cfg = self.config(c)
                t = self.team(c, p["team"])
                self.live(cfg, t)
                m, pg = self.current(c, t)
                if not m or integer(data.get("missionId"), 1, 9) != m["id"]:
                    raise HTTPException(409, "Your team has moved on. Refresh to see the current mission.")
                mid = m["id"]
                actor = p["name"]
                if action == "start":
                    if not pg["startedAt"]:
                        pg["startedAt"] = now()
                        t["startedAt"] = t["startedAt"] or now()
                        self.log(c, actor, f"Started mission {mid}", t["id"])
                    result = {"ok": True}
                elif action == "hint":
                    if not pg["startedAt"]:
                        raise HTTPException(409, "Start the mission first.")
                    idx = integer(data.get("index"), 0, 2)
                    if idx >= len(m["hints"]):
                        raise HTTPException(400, "Hint not available.")
                    if idx > 0 and idx - 1 not in pg["hints"]:
                        raise HTTPException(409, "Unlock hints in order.")
                    hint = m["hints"][idx]
                    if now() < pg["startedAt"] + hint.get("delaySeconds", 0) * 1000:
                        raise HTTPException(409, "This hint has not unlocked yet.")
                    if idx not in pg["hints"]:
                        pg["hints"].append(idx)
                        self.award(c, f"hint:{t['id']}:{mid}:{pg['generation']}:{idx}", t["id"], -hint["cost"], f"Mission {mid}: hint {idx+1}", actor, "hint", mid)
                        self.log(c, actor, f"Used hint {idx+1} on mission {mid}", t["id"])
                    result = {"ok": True, "message": "Hint unlocked"}
                elif action in {"submit", "photo"}:
                    if not pg["startedAt"]:
                        raise HTTPException(409, "Start the mission first.")
                    stage = m["stages"][pg["stageIndex"]]
                    if data.get("stageId") != stage["id"]:
                        raise HTTPException(409, "A teammate already completed this stage. Your progress has been updated.")
                    request_id = text(data.get("requestId"), 80, 8)
                    if c.execute("SELECT 1 FROM attempts WHERE request_id=?", (request_id,)).fetchone():
                        return {"ok": True, "message": "This attempt was already saved."}
                    is_photo = stage["type"] in {"photo", "team"}
                    if is_photo != (action == "photo"):
                        raise HTTPException(400, "Use the correct submission type for this stage.")
                    manual = stage.get("grading") == "manual" or (is_photo and cfg["photoMode"] == "review")
                    answer = "Photo submitted" if is_photo else validate_answer(stage, data.get("answer"))
                    correct = True if is_photo or manual else is_correct(stage, answer)
                    c.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?)", (request_id, t["id"], mid, stage["id"], pg["generation"], packed(answer), int(correct), now()))
                    used = c.execute("SELECT COUNT(*) FROM attempts WHERE team=? AND mission=? AND stage=? AND generation=?", (t["id"], mid, stage["id"], pg["generation"])).fetchone()[0]
                    terminal = correct or used >= stage["attempts"]
                    if not terminal:
                        self.log(c, actor, f"Attempted {stage['label']} on mission {mid}: not yet correct", t["id"])
                        result = {"ok": True, "correct": False, "retry": True, "remaining": stage["attempts"]-used, "message": "Not quite. Take another look and try again."}
                    else:
                        points = 0 if manual or not correct else stage["points"]
                        sid = uuid.uuid4().hex
                        submission = {"id": sid, "team": t["id"], "teamName": t["name"], "mission": mid, "missionTitle": m["title"],
                                      "stage": stage["id"], "label": stage["label"], "type": stage["type"], "prompt": stage["prompt"],
                                      "answer": answer, "photo": f"/api/photos/{sid}" if filename else None, "filename": filename,
                                      "player": actor, "at": now(), "points": points, "maxPoints": stage["points"],
                                      "status": "pending" if manual or is_photo else ("correct" if correct else "incorrect"),
                                      "manual": manual, "reviewVersion": 0, "favourite": False, "comment": ""}
                        c.execute("INSERT INTO submissions VALUES (?,?,?,?,?,?,?)", (sid, t["id"], mid, stage["id"], pg["generation"], 1, packed(submission)))
                        self.award(c, f"submission:{sid}", t["id"], points, f"{m['title']}: {stage['label']}", actor, "final" if mid == 9 else "mission", mid, stage["id"])
                        self.log(c, actor, f"Submitted {stage['label']} on mission {mid} ({points} points)", t["id"])
                        pg["stageIndex"] += 1
                        completed = pg["stageIndex"] >= len(m["stages"])
                        if completed:
                            pg["completedAt"] = now()
                            t["index"] += 1
                            if t["index"] >= 9:
                                t["completedAt"] = now()
                            self.log(c, actor, f"Completed mission {mid}", t["id"])
                        result = {"ok": True, "correct": bool(correct), "award": points, "pending": manual,
                                  "missionComplete": completed, "finished": t["index"] >= 9,
                                  "missionId": mid, "missionTitle": m["title"],
                                  "message": "Submitted for review" if manual else ("Photo saved" if is_photo else ("Correct!" if correct else "Answer saved. Keep exploring."))}
                else:
                    raise HTTPException(404, "Unknown action.")
                self.put_team(c, t)
                self.bump(c)
                return result
        except BaseException:
            if filename:
                (self.uploads / filename).unlink(missing_ok=True)
            raise

    def admin_act(self, action, data):
        with self.db(write=True) as c:
            cfg = self.config(c)
            if action == "admin/control":
                command = data.get("command")
                if command in {"start", "resume"}:
                    if command == "start" and cfg["status"] not in {"lobby", "ended"}:
                        raise HTTPException(409, "The game has already started.")
                    if command == "resume" and cfg["status"] != "paused":
                        raise HTTPException(409, "The game is not paused.")
                    verified = all(json.loads(r[0]).get("verified") for r in c.execute("SELECT doc FROM missions"))
                    if not cfg["rehearsal"] and not verified:
                        raise HTTPException(409, "Mark every mission, including the final, as recce-verified before starting a real event.")
                    if cfg["pausedAt"]:
                        delay = now() - cfg["pausedAt"]
                        cfg["pauseHistory"].append([cfg["pausedAt"], now()])
                        if cfg["deadlineAt"]:
                            cfg["deadlineAt"] += delay
                        cfg["pausedAt"] = None
                    if not cfg["startedAt"]:
                        cfg["startedAt"] = now()
                        cfg["deadlineAt"] = now() + cfg["durationMinutes"] * 60_000 if cfg["timerEnabled"] else None
                    cfg["status"] = "live"
                elif command == "pause":
                    if cfg["status"] != "live":
                        raise HTTPException(409, "Only a live game can be paused.")
                    cfg["status"], cfg["pausedAt"] = "paused", now()
                elif command == "end":
                    cfg["status"] = "ended"
                elif command == "lock":
                    cfg["leaderboardLocked"], cfg["resultsRevealed"] = True, False
                elif command == "unlock":
                    cfg["leaderboardLocked"], cfg["lockAt"] = False, 0
                elif command == "reveal":
                    cfg["resultsRevealed"] = True
                else:
                    raise HTTPException(400, "Unknown game control.")
                self.put_config(c, cfg)
                self.log(c, "Organiser", f"Game control: {command}")
            elif action == "admin/settings":
                for field in ["requireCodes", "leaderboard", "rehearsal"]:
                    if field in data:
                        if not isinstance(data[field], bool):
                            raise HTTPException(400, "Invalid setting.")
                        cfg[field] = data[field]
                for field, length in [("name", 80), ("subtitle", 100), ("venue", 100), ("helpContact", 300)]:
                    if field in data:
                        cfg[field] = text(data[field], length, 1)
                if "lockAt" in data:
                    cfg["lockAt"] = integer(data["lockAt"], 0, 8)
                if "photoMode" in data:
                    if data["photoMode"] not in {"immediate", "review"}:
                        raise HTTPException(400, "Invalid photo review mode.")
                    cfg["photoMode"] = data["photoMode"]
                if "timerEnabled" in data or "durationMinutes" in data:
                    changed = data.get("timerEnabled", cfg["timerEnabled"]) != cfg["timerEnabled"] or data.get("durationMinutes", cfg["durationMinutes"]) != cfg["durationMinutes"]
                    if cfg["startedAt"] and changed:
                        raise HTTPException(409, "Set the timer before starting. To change it, reset the event first.")
                    cfg["timerEnabled"] = bool(data.get("timerEnabled", cfg["timerEnabled"]))
                    cfg["durationMinutes"] = integer(data.get("durationMinutes", cfg["durationMinutes"]), 10, 360)
                if not cfg["rehearsal"] and cfg["status"] == "live" and any(not json.loads(r[0]).get("verified") for r in c.execute("SELECT doc FROM missions")):
                    raise HTTPException(409, "Finish verifying the missions before switching a live rehearsal into a real event.")
                self.put_config(c, cfg)
                self.log(c, "Organiser", "Updated event settings")
            elif action == "admin/mission":
                mid = integer(data.get("id"), 1, 9)
                if cfg["status"] == "live":
                    raise HTTPException(409, "Pause the event before editing missions.")
                for row in c.execute("SELECT doc FROM teams"):
                    pg = json.loads(row[0])["progress"].get(str(mid), {})
                    if pg.get("startedAt"):
                        raise HTTPException(409, "This mission has already been started. Reset it for affected teams, or reset the rehearsal event, before editing.")
                doc = validate_mission(data.get("mission"), mid)
                c.execute("UPDATE missions SET doc=? WHERE id=?", (packed(doc), mid))
                self.log(c, "Organiser", f"Edited mission {mid}: {doc['title']}")
            elif action == "admin/points":
                tid = integer(data.get("team"), 1, 8)
                self.team(c, tid)
                amount = integer(data.get("points"), -1000, 1000)
                if amount == 0:
                    raise HTTPException(400, "Choose a non-zero adjustment.")
                reason = text(data.get("reason"), 300, 3)
                rid = text(data.get("requestId"), 80, 8)
                category = "bonus" if data.get("category") == "bonus" and amount > 0 else "adjustment"
                self.award(c, f"adjustment:{rid}", tid, amount, reason, "Organiser", category)
                self.log(c, "Organiser", f"{category.title()}: {amount:+d} points. {reason}", tid)
            elif action == "admin/review":
                sid = text(data.get("id"), 50, 1)
                row = c.execute("SELECT * FROM submissions WHERE id=? AND active=1", (sid,)).fetchone()
                if not row:
                    raise HTTPException(404, "Submission no longer active.")
                sub = json.loads(row["doc"])
                if "favourite" in data:
                    sub["favourite"] = bool(data["favourite"])
                if "points" in data:
                    points = integer(data["points"], 0, sub["maxPoints"])
                    sub["reviewVersion"] += 1
                    delta = points - sub["points"]
                    sub["comment"] = text(data.get("comment", ""), 500)
                    sub["status"] = "approved" if points == sub["maxPoints"] else ("partial" if points else "rejected")
                    self.award(c, f"review:{sid}:{sub['reviewVersion']}", sub["team"], delta, f"Review: {sub['label']}" + (f". {sub['comment']}" if sub["comment"] else ""), "Organiser", "final" if sub["mission"] == 9 else "mission", sub["mission"], sub["stage"])
                    sub["points"] = points
                    sub["reviewedAt"] = now()
                    self.log(c, "Organiser", f"Reviewed {sub['label']} on mission {sub['mission']}: {points}/{sub['maxPoints']}", sub["team"])
                c.execute("UPDATE submissions SET doc=? WHERE id=?", (packed(sub), sid))
            elif action == "admin/team":
                tid = integer(data.get("team"), 1, 8)
                t = self.team(c, tid)
                if "name" in data:
                    t["name"] = text(data["name"], 40, 1)
                if data.get("code"):
                    code = text(data["code"], 32, 4).upper()
                    t["code"], t["codeHash"] = code, digest_password(code)
                if "paused" in data:
                    paused = bool(data["paused"])
                    if paused and not t["paused"]:
                        t["pauseHistory"].append([now(), None])
                    elif not paused and t["paused"] and t["pauseHistory"]:
                        t["pauseHistory"][-1][1] = now()
                    t["paused"] = paused
                self.put_team(c, t)
                self.log(c, "Organiser", "Updated team settings", tid)
            elif action == "admin/remove-player":
                pid = text(data.get("id"), 50, 1)
                p = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
                if p:
                    c.execute("DELETE FROM players WHERE id=?", (pid,))
                    self.log(c, "Organiser", f"Removed player {p['name']} and revoked their session", p["team"])
            elif action in {"admin/skip", "admin/reset-mission"}:
                tid = integer(data.get("team"), 1, 8)
                t = self.team(c, tid)
                m, pg = self.current(c, t)
                if not m:
                    raise HTTPException(409, "This team has finished.")
                reason = text(data.get("reason"), 300, 3)
                mid = m["id"]
                if action == "admin/skip":
                    pg["startedAt"] = pg["startedAt"] or now()
                    t["startedAt"] = t["startedAt"] or now()
                    pg["completedAt"], pg["skipped"] = now(), True
                    t["index"] += 1
                    if t["index"] >= 9:
                        t["completedAt"] = now()
                    self.log(c, "Organiser", f"Skipped mission {mid} without extra points. {reason}", tid)
                else:
                    if data.get("confirmation") != "RESET MISSION":
                        raise HTTPException(400, "Type RESET MISSION to confirm.")
                    totals = c.execute("SELECT category,SUM(points) AS total FROM ledger WHERE team=? AND mission=? GROUP BY category", (tid, mid)).fetchall()
                    generation = pg["generation"] + 1
                    for total in totals:
                        self.award(c, f"reset:{tid}:{mid}:{generation}:{total['category']}", tid, -total["total"], f"Reset mission {mid}. {reason}", "Organiser", total["category"], mid)
                    c.execute("UPDATE submissions SET active=0 WHERE team=? AND mission=?", (tid, mid))
                    t["progress"][str(mid)] = {"startedAt": None, "completedAt": None, "stageIndex": 0, "hints": [], "generation": generation}
                    self.log(c, "Organiser", f"Reset current mission {mid}; previous scores reversed. {reason}", tid)
                self.put_team(c, t)
            elif action == "admin/announce":
                tid = integer(data["team"], 1, 8) if data.get("team") else None
                msg = text(data.get("message"), 400, 1)
                cfg["announcements"].append({"id": uuid.uuid4().hex, "message": msg, "team": tid, "at": now()})
                cfg["announcements"] = cfg["announcements"][-100:]
                self.put_config(c, cfg)
                self.log(c, "Organiser", f"Announcement: {msg}", tid)
            elif action in {"admin/reset", "admin/reset-team"}:
                ids = list(range(1, 9)) if action == "admin/reset" else [integer(data.get("team"), 1, 8)]
                for tid in ids:
                    t = self.team(c, tid)
                    t.update({"index": 0, "progress": {}, "startedAt": None, "completedAt": None, "paused": False, "pauseHistory": []})
                    self.put_team(c, t)
                    for table in ["submissions", "attempts", "ledger", "players"]:
                        c.execute(f"DELETE FROM {table} WHERE team=?", (tid,))
                if action == "admin/reset":
                    cfg.update({"eventId": uuid.uuid4().hex, "status": "lobby", "startedAt": None, "deadlineAt": None, "pausedAt": None,
                                "pauseHistory": [], "announcements": [], "resultsRevealed": False, "leaderboardLocked": False})
                    self.put_config(c, cfg)
                self.log(c, "Organiser", "Reset game" if action == "admin/reset" else f"Reset team {ids[0]}")
            else:
                raise HTTPException(404, "Unknown organiser action.")
            self.bump(c)
        return {"ok": True, "message": "Saved"}

    def backup(self):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
        dbcopy = self.backups / f"snapshot-{stamp}.sqlite3"
        source, destination = sqlite3.connect(self.path), sqlite3.connect(dbcopy)
        try:
            source.backup(destination)
        finally:
            source.close()
            destination.close()
        archive = self.backups / f"city-hunt-backup-{stamp}.zip"
        try:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(dbcopy, "city-hunt.sqlite3")
                for photo in self.uploads.glob("*.jpg"):
                    z.write(photo, f"uploads/{photo.name}")
                z.writestr("RESTORE.txt", "Stop the server. Back up your existing data directory. Extract this archive into DATA_DIR, replacing city-hunt.sqlite3 and uploads. Remove stale city-hunt.sqlite3-wal and city-hunt.sqlite3-shm files only while the server is stopped. Keep the existing .session-secret. Restart the server. This archive contains private photos and credentials. Store it securely.\n")
        finally:
            dbcopy.unlink(missing_ok=True)
        return archive


def create_app(data_dir: str | Path | None = None, testing: bool = False) -> FastAPI:
    production = os.getenv("APP_ENV") == "production" and not testing
    directory = Path(data_dir or os.getenv("DATA_DIR", ROOT / "data"))
    public_url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    url_parts = urlparse(public_url)
    if public_url and (url_parts.username or url_parts.password or url_parts.query or url_parts.fragment or url_parts.path):
        raise RuntimeError("PUBLIC_URL must be an origin only: scheme and hostname, without a path, query or credentials.")
    if production and (not public_url.startswith("https://") or not urlparse(public_url).hostname):
        raise RuntimeError("Set PUBLIC_URL to the HTTPS address players will open.")
    store = Store(directory, production, os.getenv("ADMIN_PASSWORD"))
    secret_path = directory / ".session-secret"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_urlsafe(48))
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
    app = FastAPI(title="CITY HUNT", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET") or secret_path.read_text().strip(),
                       session_cookie="cityhunt_session", max_age=14*24*60*60, same_site="lax", https_only=production)
    if production:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(public_url).hostname, "localhost", "127.0.0.1", "healthcheck.railway.app"])

    @app.middleware("http")
    async def headers(request: Request, call_next):
        try:
            if int(request.headers.get("content-length", "0")) > MAX_BODY:
                return JSONResponse({"error": "Upload too large. Choose a smaller photo."}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "Invalid content length."}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/photos/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def errors(request, exc):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        request.session.setdefault("csrf", secrets.token_urlsafe(24))
        return store.bootstrap(request.session)

    @app.get("/api/state")
    def state(request: Request):
        return store.state(request.session)

    @app.get("/api/admin")
    def admin_state(request: Request):
        return store.state(request.session, admin=True)

    @app.post("/api/{action:path}")
    async def action(request: Request, action: str):
        csrf = request.session.get("csrf", "")
        if not csrf or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
            raise HTTPException(403, "Session verification failed. Refresh the page and retry.")
        origin = request.headers.get("origin")
        allowed = public_url or str(request.base_url).rstrip("/")
        if origin and origin != allowed:
            raise HTTPException(403, "Requests must come from the game's own website.")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "Use a JSON request.")
        parts, size = [], 0
        async for part in request.stream():
            size += len(part)
            if size > MAX_BODY:
                raise HTTPException(413, "Upload too large.")
            parts.append(part)
        try:
            data = json.loads(b"".join(parts))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Request is not valid JSON.")
        return await run_in_threadpool(store.act, action, data, request.session, request.client.host if request.client else "unknown")

    @app.get("/api/photos/{submission_id}")
    def photo(submission_id: str, request: Request):
        with store.db() as c:
            row = c.execute("SELECT team,doc FROM submissions WHERE id=? AND active=1", (submission_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Photo not found.")
            if not store.admin(request.session):
                p = store.player(c, request.session)
                if p["team"] != row["team"]:
                    raise HTTPException(403, "This photo belongs to another team.")
            doc = json.loads(row["doc"])
            name = doc.get("filename")
            if not name or not re.fullmatch(r"[a-f0-9]{40}\.jpg", name) or not (store.uploads / name).is_file():
                raise HTTPException(404, "Photo not found.")
            return FileResponse(store.uploads / name, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/export")
    def export(request: Request, kind: str = "scores"):
        store.require_admin(request.session)
        if kind not in {"scores", "submissions", "ledger"}:
            raise HTTPException(400, "Unknown export type.")
        payload = store.state(request.session, admin=True)
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        def safe(x):
            if isinstance(x, (list, dict)):
                x = packed(x)
            if isinstance(x, str) and x.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                return "'" + x
            return x
        if kind == "submissions":
            fields = ["teamName", "mission", "missionTitle", "label", "type", "player", "at", "answer", "points", "maxPoints", "status", "comment"]
            writer.writerow(fields)
            for sub in payload["submissions"]:
                writer.writerow([safe(sub.get(k, "")) for k in fields])
        elif kind == "ledger":
            fields = ["team", "mission", "stage", "category", "points", "reason", "actor", "at"]
            writer.writerow(fields)
            for entry in payload["ledger"]:
                writer.writerow([safe(entry.get(k, "")) for k in fields])
        else:
            writer.writerow(["Team", "Score", "Missions completed", "Started (UTC ms)", "Finished (UTC ms)", "Elapsed seconds (wall clock)", "Pending reviews"])
            for t in payload["teams"]:
                elapsed = (t["completedAt"] - t["startedAt"])/1000 if t["completedAt"] and t["startedAt"] else ""
                writer.writerow([safe(t["name"]), t["score"], min(t["index"], 8), t["startedAt"] or "", t["completedAt"] or "", elapsed, sum(s["status"] == "pending" and s["team"] == t["id"] for s in payload["submissions"])])
        return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="city-hunt-{kind}.csv"'})

    @app.get("/api/qr")
    def qr(request: Request, team: int | None = None):
        store.require_admin(request.session)
        url = public_url or str(request.base_url).rstrip("/")
        if team is not None:
            integer(team, 1, 8)
            url += f"/?team={team}"
        image = qrcode.make(url)
        out = io.BytesIO()
        image.save(out, format="PNG")
        return Response(out.getvalue(), media_type="image/png", headers={"Content-Disposition": 'inline; filename="city-hunt-join-qr.png"'})

    @app.get("/api/backup")
    def backup(request: Request):
        store.require_admin(request.session)
        archive = store.backup()
        return FileResponse(archive, media_type="application/zip", filename=archive.name)

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    @app.get("/admin")
    @app.get("/results")
    def index():
        return FileResponse(ROOT / "static" / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})

    return app
