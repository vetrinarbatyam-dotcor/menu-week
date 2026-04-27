"""שבוע טעים — POC backend.
FastAPI app: serves API + static frontend on port 3015.
Uses `claude -p` (Claude Max) for AI menu generation.
SQLite at data/app.db for saved menus, favorites, custom recipes.
"""
import json
import logging
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("menu-week")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FRONTEND = ROOT / "frontend"
DB_PATH = DATA / "app.db"

DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
MEALS = ["breakfast", "lunch", "dinner"]
MEALS_HE = {"breakfast": "בוקר", "lunch": "צהריים", "dinner": "ערב"}

# ── seed recipes (immutable catalog) ──
with open(DATA / "recipes.json", encoding="utf-8") as f:
    SEED_RECIPES: list[dict[str, Any]] = json.load(f)


# ── sqlite ──
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS saved_menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            week_json TEXT NOT NULL,
            shopping_json TEXT NOT NULL,
            ai_used INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS favorites (
            recipe_id TEXT PRIMARY KEY,
            added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS custom_recipes (
            id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
    log.info("DB initialized at %s", DB_PATH)


def all_recipes() -> list[dict]:
    """Combine seed + custom recipes, marking favorites."""
    with db() as conn:
        favs = {row["recipe_id"] for row in conn.execute("SELECT recipe_id FROM favorites")}
        custom_rows = conn.execute("SELECT data_json FROM custom_recipes").fetchall()
    custom = [json.loads(r["data_json"]) for r in custom_rows]
    out = []
    for r in [*SEED_RECIPES, *custom]:
        rec = {**r, "is_favorite": r["id"] in favs, "is_custom": r in custom}
        out.append(rec)
    return out


def recipes_by_id() -> dict[str, dict]:
    return {r["id"]: r for r in all_recipes()}


# ── pydantic models ──
class MenuRequest(BaseModel):
    week_start: str | None = None
    style_hint: str | None = None
    surprise: bool = False
    favorites_only: bool = False
    max_prep_minutes: int = 30  # תקרת זמן לערב (30/45/60/90)


class SaveMenuRequest(BaseModel):
    name: str
    week_data: dict


class CustomRecipeRequest(BaseModel):
    name: str
    cuisine: str  # israeli/italian/asian/middle_eastern/mexican/healthy/american/other
    meal_type: str  # breakfast/lunch/dinner
    prep_minutes: int
    difficulty: str = "easy"
    protein_level: str = "medium"
    carb_level: str = "medium"
    tags: list[str] = []
    ingredients: list[dict] = []  # [{item, qty, unit, category}]
    steps: list[str] = []


# ── app ──
app = FastAPI(title="שבוע טעים", version="0.2.0")
init_db()


# ── claude helper ──
def call_claude(prompt: str, timeout: int = 120) -> str | None:
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            log.warning("claude rc=%d stderr=%s", result.returncode, result.stderr[:300])
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        log.warning("claude timeout %ds", timeout)
        return None
    except Exception as e:
        log.exception("claude failed: %s", e)
        return None


def extract_json(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        for opener in "[{":
            i = text.find(opener)
            if i >= 0:
                text = text[i:]
                break
    return json.loads(text)


# ── menu generation ──
def build_menu_prompt(recipes: list[dict], style_hint: str | None, max_prep_minutes: int = 30) -> str:
    catalog = [{
        "id": r["id"], "name": r["name"], "cuisine": r["cuisine"],
        "meal_type": r["meal_type"], "prep_minutes": r["prep_minutes"],
        "protein_level": r["protein_level"], "carb_level": r["carb_level"],
        "tags": r["tags"], "favorite": r.get("is_favorite", False),
    } for r in recipes]
    style_line = f"\n## דגש מיוחד השבוע: {style_hint}" if style_hint else ""
    return f"""אתה שף תכנון תפריטים. בנה תפריט שבועי למשפחה.

## פרופיל המשפחה
- 2 מבוגרים + 4 ילדים (גילים 11, 15, 17, 19)
- צהריים בבית: 11, 15, 17 (ה-19 לא חוזר לצהריים)
- זמן בישול ערב מקסימלי השבוע: {max_prep_minutes} דקות (לשישי/שבת/אירוח אפשר לחרוג קצת)
- העדפה: חלבון גבוה + דל פחמימות, אבל גמיש
- סגנונות: ישראלי, איטלקי, אסיאתי, מזרח-תיכוני, מקסיקני, בריא
- **לא אמריקאי** (חוץ מפנקייקס בסופ״ש)
- שישי = ערב חגיגי
- שבת בוקר/צהריים = בעיקר שאריות מהיום הקודם
- מתכונים עם favorite=true הם מועדפים — תן להם עדיפות{style_line}

## מאגר המתכונים (בחר רק מ-id-ים אלה!)
{json.dumps(catalog, ensure_ascii=False, indent=2)}

## משימה
בנה תפריט 7 ימים × 3 ארוחות = 21 ארוחות.
שישי בערב חגיגי. שבת בוקר/צהריים פשוט/שאריות.

## פלט (JSON בלבד)
[
  {{"day": "ראשון", "breakfast": "recipe_id", "lunch": "recipe_id", "dinner": "recipe_id"}},
  ...
  {{"day": "שבת", "breakfast": "recipe_id", "lunch": "recipe_id", "dinner": "recipe_id"}}
]

החזר רק JSON, ללא טקסט נוסף."""


def fallback_menu(recipes: list[dict]) -> list[dict]:
    import random
    by_meal = defaultdict(list)
    for r in recipes:
        by_meal[r["meal_type"]].append(r["id"])
    pool = [r["id"] for r in recipes]
    return [{
        "day": day,
        "breakfast": random.choice(by_meal.get("breakfast", pool)),
        "lunch": random.choice(by_meal.get("lunch", pool)),
        "dinner": random.choice(by_meal.get("dinner", pool)),
    } for day in DAYS_HE]


def enrich_menu(menu_raw: list[dict]) -> list[dict]:
    recs = recipes_by_id()
    out = []
    for day in menu_raw:
        row = {"day": day["day"], "meals": {}}
        for meal in MEALS:
            rid = day.get(meal)
            if rid and rid in recs:
                r = recs[rid]
                row["meals"][meal] = {
                    "id": r["id"], "name": r["name"], "cuisine": r["cuisine"],
                    "prep_minutes": r["prep_minutes"], "tags": r["tags"],
                    "protein_level": r["protein_level"], "carb_level": r["carb_level"],
                    "is_favorite": r.get("is_favorite", False),
                }
            else:
                row["meals"][meal] = None
        out.append(row)
    return out


def build_shopping_list(menu_raw: list[dict]) -> list[dict]:
    recs = recipes_by_id()
    by_category: dict[str, dict[str, dict]] = defaultdict(dict)
    for day in menu_raw:
        for meal in MEALS:
            rid = day.get(meal)
            if not rid or rid not in recs:
                continue
            for ing in recs[rid]["ingredients"]:
                cat = ing["category"]
                key = f"{ing['item']}|{ing['unit']}"
                if key in by_category[cat]:
                    by_category[cat][key]["qty"] += ing["qty"]
                else:
                    by_category[cat][key] = {
                        "item": ing["item"], "qty": ing["qty"], "unit": ing["unit"],
                    }
    return [{
        "category": cat,
        "items": sorted(by_category[cat].values(), key=lambda x: x["item"]),
    } for cat in sorted(by_category.keys())]


# ══════════ ENDPOINTS ══════════

# ── recipes ──
@app.get("/api/recipes")
def list_recipes(favorites_only: bool = False):
    recs = all_recipes()
    if favorites_only:
        recs = [r for r in recs if r["is_favorite"]]
    return {"ok": True, "data": recs}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    r = recipes_by_id().get(recipe_id)
    if not r:
        raise HTTPException(404, "מתכון לא נמצא")
    return {"ok": True, "data": r}


@app.post("/api/recipes")
def add_custom_recipe(req: CustomRecipeRequest):
    rid = re.sub(r"[^a-z0-9_]", "_", req.name.lower().replace(" ", "_"))
    rid = f"custom_{rid}_{int(datetime.now().timestamp())}"
    data = req.model_dump()
    data["id"] = rid
    with db() as conn:
        conn.execute(
            "INSERT INTO custom_recipes (id, data_json, created_at) VALUES (?, ?, ?)",
            (rid, json.dumps(data, ensure_ascii=False), datetime.now().isoformat()),
        )
    log.info("added custom recipe %s", rid)
    return {"ok": True, "data": data}


@app.delete("/api/recipes/{recipe_id}")
def delete_custom_recipe(recipe_id: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM custom_recipes WHERE id = ?", (recipe_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "מתכון מותאם אישית לא נמצא (או seed)")
    return {"ok": True}


# ── favorites ──
@app.post("/api/recipes/{recipe_id}/favorite")
def toggle_favorite(recipe_id: str):
    if recipe_id not in recipes_by_id():
        raise HTTPException(404, "מתכון לא נמצא")
    with db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM favorites WHERE recipe_id = ?", (recipe_id,)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM favorites WHERE recipe_id = ?", (recipe_id,))
            return {"ok": True, "is_favorite": False}
        conn.execute(
            "INSERT INTO favorites (recipe_id, added_at) VALUES (?, ?)",
            (recipe_id, datetime.now().isoformat()),
        )
        return {"ok": True, "is_favorite": True}


# ── menu ──
@app.post("/api/menu/generate")
def generate_menu(req: MenuRequest):
    log.info("generate surprise=%s style=%s favs=%s", req.surprise, req.style_hint, req.favorites_only)
    style = req.style_hint
    if req.surprise:
        style = (style + " · " if style else "") + "הפתע אותי — מגוון מקסימלי וכמה מנות פחות שגרתיות"

    pool = all_recipes()
    if req.favorites_only:
        favs = [r for r in pool if r["is_favorite"]]
        if len(favs) >= 6:  # need enough variety
            pool = favs
        else:
            log.warning("favorites_only requested but only %d favorites — using full pool", len(favs))

    prompt = build_menu_prompt(pool, style, req.max_prep_minutes)
    raw_out = call_claude(prompt, timeout=180)
    used_fallback = False
    if raw_out:
        try:
            menu_raw = extract_json(raw_out)
            if not isinstance(menu_raw, list) or len(menu_raw) != 7:
                raise ValueError("non-7-day menu")
        except Exception as e:
            log.warning("parse failed (%s); fallback", e)
            menu_raw = fallback_menu(pool)
            used_fallback = True
    else:
        menu_raw = fallback_menu(pool)
        used_fallback = True

    return {
        "ok": True,
        "data": {
            "week": enrich_menu(menu_raw),
            "shopping_list": build_shopping_list(menu_raw),
            "ai_used": not used_fallback,
            "raw_menu": menu_raw,
        },
    }


# ── saved menus ──
@app.post("/api/menus")
def save_menu(req: SaveMenuRequest):
    week = req.week_data.get("week", [])
    shopping = req.week_data.get("shopping_list", [])
    ai = 1 if req.week_data.get("ai_used") else 0
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO saved_menus (name, created_at, week_json, shopping_json, ai_used) VALUES (?, ?, ?, ?, ?)",
            (req.name, datetime.now().isoformat(),
             json.dumps(week, ensure_ascii=False),
             json.dumps(shopping, ensure_ascii=False), ai),
        )
        new_id = cur.lastrowid
    log.info("saved menu id=%d name=%s", new_id, req.name)
    return {"ok": True, "id": new_id}


@app.get("/api/menus")
def list_menus():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, ai_used FROM saved_menus ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "data": [dict(r) for r in rows]}


@app.get("/api/menus/{menu_id}")
def get_menu(menu_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM saved_menus WHERE id = ?", (menu_id,)).fetchone()
    if not row:
        raise HTTPException(404, "תפריט לא נמצא")
    return {
        "ok": True,
        "data": {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "ai_used": bool(row["ai_used"]),
            "week": json.loads(row["week_json"]),
            "shopping_list": json.loads(row["shopping_json"]),
        },
    }


@app.delete("/api/menus/{menu_id}")
def delete_menu(menu_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM saved_menus WHERE id = ?", (menu_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "תפריט לא נמצא")
    return {"ok": True}


# ── static + health ──
if FRONTEND.exists():
    @app.get("/")
    def root():
        return FileResponse(FRONTEND / "index.html")

    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/health")
def health():
    with db() as conn:
        saved = conn.execute("SELECT COUNT(*) c FROM saved_menus").fetchone()["c"]
        favs = conn.execute("SELECT COUNT(*) c FROM favorites").fetchone()["c"]
        custom = conn.execute("SELECT COUNT(*) c FROM custom_recipes").fetchone()["c"]
    return {
        "ok": True,
        "recipes": len(SEED_RECIPES) + custom,
        "saved_menus": saved,
        "favorites": favs,
        "custom_recipes": custom,
    }
