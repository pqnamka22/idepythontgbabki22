import os
import sys
import sqlite3
import subprocess
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from aiogram.utils import executor

# ===================== CONFIG =====================
BOT_TOKEN = "8288247421:AAG7jVr3v5ha9AeS_b_i1_7zA3mrqgbdt0M"
ADMIN_FREE_ID = 6185460659

BASE_DIR = "sandbox"
DB_PATH = "db.sqlite"

FREE_TIMEOUT = 5
PLUS_TIMEOUT = 60
PRO_TIMEOUT = 120

STARS_PLUS_MONTH = 100
STARS_PLUS_YEAR = 900
STARS_PRO_MONTH = 200
STARS_PRO_YEAR = 1800

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
        if uid == ADMIN_FREE_ID:
            plan, until = "pro", None
        else:
            plan, until = "free", None
        cur.execute("INSERT INTO users VALUES (?,?,?,?)", (uid, username, plan, until))
        db.commit()
        return plan, until
    return r

def check_plan(uid):
    plan, until = get_user(uid)
    if plan in ["plus", "pro"] and until:
        if datetime.now() > datetime.fromisoformat(until):
            cur.execute("UPDATE users SET plan='free', until=NULL WHERE user_id=?", (uid,))
            db.commit()
            return "free"
    return plan

def activate_plan(uid, plan, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    cur.execute("UPDATE users SET plan=?, until=? WHERE user_id=?", (plan, until, uid))
    db.commit()

# ===================== TELEGRAM =====================
bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ---------- START ----------
@dp.message_handler(commands=["start"])
async def start(m: types.Message):
    plan = check_plan(m.from_user.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📂 Мои проекты", callback_data="projects"))
    kb.add(InlineKeyboardButton("➕ Новый проект", callback_data="newproject"))
    kb.add(InlineKeyboardButton("⚡ IDE / Run", callback_data="runproject"))
    kb.add(InlineKeyboardButton("📦 Pip / Test", callback_data="piptest"))
    kb.add(InlineKeyboardButton("⭐ Подписки", callback_data="subscribe"))
    await m.answer(
        f"🧠 Python IDE\nТекущий план: {plan}\nВыберите действие:",
        reply_markup=kb
    )

# ================= CALLBACK HANDLER =================
@dp.callback_query_handler(lambda c: True)
async def callback_handler(c: types.CallbackQuery):
    uid = c.from_user.id
    data = c.data
    if data == "projects":
        cur.execute("SELECT name FROM projects WHERE user_id=?", (uid,))
        rows = cur.fetchall()
        msg = "📂 Проекты:\n" + "\n".join(r[0] for r in rows) if rows else "📂 Проектов нет"
        await c.message.edit_text(msg)
    elif data == "newproject":
        await c.message.answer("Введите имя нового проекта:")
        # Вставим следующий ввод через хендлер
    elif data == "runproject":
        await c.message.answer("Введите имя проекта для запуска:")
    elif data == "piptest":
        plan = check_plan(uid)
        if plan == "free":
            await c.message.answer("🔒 Pip и тесты доступны только Plus / Pro")
        else:
            await c.message.answer("Введите команду для pip или тестов (/pip <project> <pkg> или /test <project>)")
    elif data == "subscribe":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(f"⭐ Plus 30 дней — {STARS_PLUS_MONTH} Stars", pay=True))
        kb.add(InlineKeyboardButton(f"⭐ Plus 365 дней — {STARS_PLUS_YEAR} Stars", pay=True))
        kb.add(InlineKeyboardButton(f"👑 Pro 30 дней — {STARS_PRO_MONTH} Stars", pay=True))
        kb.add(InlineKeyboardButton(f"👑 Pro 365 дней — {STARS_PRO_YEAR} Stars", pay=True))
        await c.message.answer("Выберите подписку:", reply_markup=kb)

# ===================== MESSAGE HANDLERS =====================
@dp.message_handler(commands=["newproject"])
async def new_project(m):
    name = m.get_args().strip()
    if not name:
        await m.answer("❌ /newproject <имя>")
        return
    cur.execute("INSERT INTO projects (user_id,name) VALUES (?,?)", (m.from_user.id, name))
    db.commit()
    path = project_dir(m.from_user.id, name)
    open(os.path.join(path, "main.py"), "w").write("# ваш код\n")
    await m.answer(f"📁 Проект `{name}` создан")

@dp.message_handler(commands=["projects"])
async def projects(m):
    cur.execute("SELECT name FROM projects WHERE user_id=?", (m.from_user.id,))
    rows = cur.fetchall()
    if not rows:
        await m.answer("📂 Проектов нет")
        return
    await m.answer("📂 Проекты:\n" + "\n".join(r[0] for r in rows))

@dp.message_handler(commands=["run"])
async def run(m):
    project = m.get_args().strip()
    if not project:
        await m.answer("/run <project>")
        return
    plan = check_plan(m.from_user.id)
    timeout = {"free": FREE_TIMEOUT, "plus": PLUS_TIMEOUT, "pro": PRO_TIMEOUT}[plan]
    path = project_dir(m.from_user.id, project)
    file = os.path.join(path, "main.py")
    if not os.path.exists(file):
        await m.answer("❌ main.py не найден")
        return
    try:
        p = subprocess.run([sys.executable, "main.py"], cwd=path, timeout=timeout, capture_output=True, text=True)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        out = "⏱ timeout"
    await m.answer(f"```\n{out[:4000]}\n```", parse_mode="Markdown")

@dp.message_handler(commands=["pip"])
async def pip_cmd(m):
    plan = check_plan(m.from_user.id)
    if plan not in ["plus", "pro"]:
        await m.answer("🔒 Pip доступен только Plus / Pro")
        return
    args = m.get_args().split()
    if len(args) < 2:
        await m.answer("/pip <project> <pkg>")
        return
    project, pkg = args[0], args[1]
    path = project_dir(m.from_user.id, project)
    p = subprocess.run([sys.executable, "-m", "pip", "install", pkg], cwd=path, capture_output=True, text=True)
    await m.answer(p.stdout[-4000:] or p.stderr[-4000:])

@dp.message_handler(commands=["test"])
async def test(m):
    plan = check_plan(m.from_user.id)
    if plan not in ["plus", "pro"]:
        await m.answer("🔒 Тесты доступны только Plus / Pro")
        return
    project = m.get_args().strip()
    if not project:
        await m.answer("/test <project>")
        return
    path = project_dir(m.from_user.id, project)
    p = subprocess.run(["pytest"], cwd=path, capture_output=True, text=True)
    await m.answer(p.stdout[-4000:] or p.stderr[-4000:])

# ===================== STARS PAYMENTS =====================
@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def stars_payment(m: types.Message):
    pay = m.successful_payment
    if pay.currency != "XTR":
        return
    uid = m.from_user.id
    if pay.total_amount == STARS_PLUS_MONTH:
        activate_plan(uid, "plus", 30)
        await m.answer("⭐ Plus активирован на 30 дней")
    elif pay.total_amount == STARS_PLUS_YEAR:
        activate_plan(uid, "plus", 365)
        await m.answer("⭐ Plus активирован на 1 год")
    elif pay.total_amount == STARS_PRO_MONTH:
        activate_plan(uid, "pro", 30)
        await m.answer("👑 Pro активирован на 30 дней")
    elif pay.total_amount == STARS_PRO_YEAR:
        activate_plan(uid, "pro", 365)
        await m.answer("👑 Pro активирован на 1 год")

# ===================== RUN =====================
if __name__ == "__main__":
    executor.start_polling(dp)
