import os, secrets, sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

DB = os.getenv("DATABASE_PATH", "clinic.db")
ADMIN_KEY = os.getenv("ADMIN_KEY", "change-this-admin-key")
app = FastAPI(title="Clinic Secretary MVP")

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), clinic_name TEXT DEFAULT 'مطب', base_fee INTEGER DEFAULT 0);
        INSERT OR IGNORE INTO settings(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS banks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, card_number TEXT NOT NULL, holder TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, starts_at TEXT UNIQUE NOT NULL, enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY, patient TEXT NOT NULL, phone TEXT NOT NULL, slot_id INTEGER NOT NULL, amount INTEGER NOT NULL, status TEXT DEFAULT 'pending', expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
        """)

init_db()

def page(content):
    return HTMLResponse(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>منشی مطب</title><style>body{{font-family:tahoma;max-width:900px;margin:24px auto;padding:0 14px;background:#f5f6f8}}section{{background:white;padding:16px;margin:12px 0;border-radius:12px}}input,select,button{{padding:10px;margin:5px;border:1px solid #bbb;border-radius:7px}}button{{background:#155eef;color:white}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:right}}</style><h2>پنل منشی مطب</h2>{content}</html>""")

@app.get("/", response_class=HTMLResponse)
def home():
    with connect() as c:
        slots = c.execute("SELECT * FROM slots WHERE enabled=1 ORDER BY starts_at").fetchall()
        bookings = c.execute("SELECT b.*,s.starts_at FROM bookings b JOIN slots s ON s.id=b.slot_id ORDER BY b.id DESC").fetchall()
        banks = c.execute("SELECT * FROM banks").fetchall()
        settings = c.execute("SELECT * FROM settings WHERE id=1").fetchone()
    opts = "".join(f'<option value="{s["id"]}">{s["starts_at"]}</option>' for s in slots)
    bank_rows = "".join(f'<li>{b["title"]} — {b["card_number"]} — {b["holder"]}</li>' for b in banks)
    rows = "".join(f'<tr><td>{b["patient"]}</td><td>{b["phone"]}</td><td>{b["starts_at"]}</td><td>{b["amount"]:,}</td><td>{b["status"]}</td><td><form method="post" action="/admin/confirm"><input type="hidden" name="booking_id" value="{b["id"]}"><input name="key" type="password" placeholder="کلید مدیر"><button>تأیید دستی</button></form></td></tr>' for b in bookings)
    return page(f"""
    <section><h3>تنظیمات مطب</h3><form method="post" action="/admin/settings"><input name="clinic_name" value="{settings['clinic_name']}"><input name="base_fee" type="number" value="{settings['base_fee']}"><input name="key" type="password" placeholder="کلید مدیر"><button>ذخیره</button></form></section>
    <section><h3>تعریف ساعت آزاد</h3><form method="post" action="/admin/slots"><input name="starts_at" placeholder="2026-11-20 09:00" required><input name="key" type="password" placeholder="کلید مدیر"><button>افزودن</button></form></section>
    <section><h3>کارت‌های بانکی</h3><form method="post" action="/admin/banks"><input name="title" placeholder="بانک"><input name="card_number" placeholder="شماره کارت"><input name="holder" placeholder="صاحب کارت"><input name="key" type="password" placeholder="کلید مدیر"><button>افزودن کارت</button></form><ul>{bank_rows}</ul></section>
    <section><h3>ثبت رزرو آزمایشی</h3><form method="post" action="/book"><input name="patient" placeholder="نام بیمار" required><input name="phone" placeholder="شماره تماس" required><select name="slot_id" required>{opts}</select><button>ثبت رزرو</button></form></section>
    <section><h3>نوبت‌ها</h3><table><tr><th>بیمار</th><th>تلفن</th><th>زمان</th><th>مبلغ</th><th>وضعیت</th><th>عملیات</th></tr>{rows}</table></section>
    """)

def require_admin(key):
    if not secrets.compare_digest(key, ADMIN_KEY):
        raise HTTPException(403, "کلید مدیر نادرست است")

@app.post("/admin/settings")
def save_settings(clinic_name: str=Form(...), base_fee: int=Form(...), key: str=Form(...)):
    require_admin(key)
    if base_fee < 0: raise HTTPException(400, "مبلغ نامعتبر است")
    with connect() as c:
        c.execute("UPDATE settings SET clinic_name=?,base_fee=? WHERE id=1", (clinic_name, base_fee))
    return RedirectResponse("/", 303)

@app.post("/admin/slots")
def add_slot(starts_at: str=Form(...), key: str=Form(...)):
    require_admin(key)
    try: datetime.strptime(starts_at, "%Y-%m-%d %H:%M")
    except ValueError: raise HTTPException(400, "قالب زمان: YYYY-MM-DD HH:MM")
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO slots(starts_at) VALUES(?)", (starts_at,))
    return RedirectResponse("/", 303)

@app.post("/admin/banks")
def add_bank(title: str=Form(...), card_number: str=Form(...), holder: str=Form(...), key: str=Form(...)):
    require_admin(key)
    with connect() as c:
        c.execute("INSERT INTO banks(title,card_number,holder) VALUES(?,?,?)", (title, card_number, holder))
    return RedirectResponse("/", 303)

@app.post("/admin/confirm")
def confirm(booking_id: int=Form(...), key: str=Form(...)):
    require_admin(key)
    with connect() as c:
        c.execute("UPDATE bookings SET status='confirmed' WHERE id=? AND status='pending'", (booking_id,))
    return RedirectResponse("/", 303)

@app.post("/book", response_class=HTMLResponse)
def book(patient: str=Form(...), phone: str=Form(...), slot_id: int=Form(...)):
    now = datetime.now()
    with connect() as c:
        slot = c.execute("SELECT * FROM slots WHERE id=? AND enabled=1", (slot_id,)).fetchone()
        if not slot: raise HTTPException(404, "ساعت انتخاب‌شده موجود نیست")
        active = c.execute("SELECT 1 FROM bookings WHERE slot_id=? AND status IN ('pending','confirmed') AND (status='confirmed' OR expires_at>?)", (slot_id, now.isoformat())).fetchone()
        if active: raise HTTPException(409, "این ساعت قبلاً رزرو شده است")
        fee = c.execute("SELECT base_fee FROM settings WHERE id=1").fetchone()["base_fee"]
        amount = int(fee) + secrets.randbelow(999) + 1
        expires = (now + timedelta(minutes=15)).isoformat(timespec="seconds")
        cur = c.execute("INSERT INTO bookings(patient,phone,slot_id,amount,expires_at,created_at) VALUES(?,?,?,?,?,?)", (patient,phone,slot_id,amount,expires,now.isoformat(timespec="seconds")))
        booking_id = cur.lastrowid
    return page(f'<section><h3>رزرو آزمایشی ثبت شد</h3><p>کد پیگیری: {booking_id}</p><p>مبلغ اختصاصی: <b>{amount:,} تومان</b></p><p>مهلت رزرو: ۱۵ دقیقه</p><p>پرداخت هنوز خودکار بررسی نمی‌شود؛ تأیید فقط باید پس از بررسی واقعی توسط منشی انجام شود.</p><a href="/">بازگشت</a></section>')
