import os
import sys
import sqlite3
import subprocess
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import LabeledPrice
from aiogram.utils import executor

# ===================== CONFIG =====================

BOT_TOKEN = "8288247421:AAG7jVr3v5ha9AeS_b_i1_7zA3mrqgbdt0M"

BASE_DIR = "sandbox"
DB_PATH = "db.sqlite"

FREE_TIMEOUT = 5
PLUS_TIMEOUT = 60

STARS_MONTH = 100
STARS_YEAR = 900

os.makedirs(BASE_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO)

# ===================== DATABASE =====================

db = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    plan TEXT,
    until TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT
)
""")

db.commit()

# ===================== UTILS =====================

def user_dir(uid):
    p = os.path.join(BASE_DIR, f"user_{uid}")
    os.makedirs(p, exist_ok=True)
    return p

def project_dir(uid, name):
    p = os.path.join(user_dir(uid), name)
    os.makedirs(p, exist_ok=True)
    return p

def get_user(uid, username=""):
    cur.execute("SELECT plan, until FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        cur.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            (uid, username, "free", None)
        )
        db.commit()
        return "free", None
    return r

def check_plan(uid):
    plan, until = get_user(uid)
    if plan == "plus" and until:
        if datetime.now() > datetime.fromisoformat(until):
            cur.execute(
                "UPDATE users SET plan='free', until=NULL WHERE user_id=?",
                (uid,)
            )
            db.commit()
            return "free"
    return plan

def activate_plus(uid, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    cur.execute(
        "UPDATE users SET plan='plus', until=? WHERE user_id=?",
        (until, uid)
    )
    db.commit()

# ===================== TELEGRAM =====================

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ---------- START ----------

@dp.message_handler(commands=["start"])
async def start(m: types.Message):
    plan = check_plan(m.from_user.id)
    await m.answer(
        f"🧠 Python IDE\n"
        f"План: {plan}\n\n"
        f"/projects\n"
        f"/newproject <name>\n"
        f"/run <project>\n"
        f"/pip <project> install pkg\n"
        f"/test <project>\n"
        f"/subscribe"
    )

# ---------- PROJECTS ----------

@dp.message_handler(commands=["projects"])
async def projects(m):
    cur.execute(
        "SELECT name FROM projects WHERE user_id=?",
        (m.from_user.id,)
    )
    rows = cur.fetchall()
    if not rows:
        await m.answer("📂 Проектов нет")
        return
    await m.answer("📂 Проекты:\n" + "\n".join(r[0] for r in rows))

@dp.message_handler(commands=["newproject"])
async def new_project(m):
    name = m.get_args().strip()
    if not name:
        await m.answer("❌ /newproject name")
        return

    cur.execute(
        "INSERT INTO projects (user_id, name) VALUES (?,?)",
        (m.from_user.id, name)
    )
    db.commit()

    path = project_dir(m.from_user.id, name)
    open(os.path.join(path, "main.py"), "w").write("# your code\n")

    await m.answer(f"📁 Проект `{name}` создан")

# ---------- RUN ----------

@dp.message_handler(commands=["run"])
async def run(m):
    project = m.get_args().strip()
    if not project:
        await m.answer("/run project_name")
        return

    plan = check_plan(m.from_user.id)
    timeout = PLUS_TIMEOUT if plan == "plus" else FREE_TIMEOUT

    path = project_dir(m.from_user.id, project)
    file = os.path.join(path, "main.py")

    if not os.path.exists(file):
        await m.answer("❌ main.py не найден")
        return

    try:
        p = subprocess.run(
            [sys.executable, "main.py"],
            cwd=path,
            timeout=timeout,
            capture_output=True,
            text=True
        )
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        out = "⏱ timeout"

    await m.answer(f"```\n{out[:4000]}\n```", parse_mode="Markdown")

# ---------- PIP ----------

@dp.message_handler(commands=["pip"])
async def pip_cmd(m):
    if check_plan(m.from_user.id) != "plus":
        await m.answer("🔒 pip только Plus")
        return

    args = m.get_args().split()
    if len(args) < 2:
        await m.answer("/pip project install pkg")
        return

    project, pkg = args[0], args[-1]
    path = project_dir(m.from_user.id, project)

    p = subprocess.run(
        [sys.executable, "-m", "pip", "install", pkg],
        cwd=path,
        capture_output=True,
        text=True
    )
    await m.answer(p.stdout[-4000:] or p.stderr[-4000:])

# ---------- TEST ----------

@dp.message_handler(commands=["test"])
async def test(m):
    project = m.get_args().strip()
    if not project:
        await m.answer("/test project")
        return

    path = project_dir(m.from_user.id, project)
    p = subprocess.run(
        ["pytest"],
        cwd=path,
        capture_output=True,
        text=True
    )
    await m.answer(p.stdout[-4000:] or p.stderr[-4000:])

# ===================== STARS PAYMENTS =====================

@dp.message_handler(commands=["subscribe"])
async def subscribe(m):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⭐ Plus 30 дней — 100 Stars", pay=True))
    kb.add(types.InlineKeyboardButton("👑 Plus 365 дней — 900 Stars", pay=True))

    await bot.send_message(
        chat_id=m.chat.id,
        text="Выбери подписку:",
        reply_markup=kb
    )

@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def stars_payment(m: types.Message):
    pay = m.successful_payment

    if pay.currency != "XTR":
        return

    if pay.total_amount == STARS_MONTH:
        activate_plus(m.from_user.id, 30)
        await m.answer("⭐ Plus активирован на 30 дней")

    elif pay.total_amount == STARS_YEAR:
        activate_plus(m.from_user.id, 365)
        await m.answer("👑 Plus активирован на 1 год")

# ===================== START =====================

if __name__ == "__main__":
    executor.start_polling(dp)
