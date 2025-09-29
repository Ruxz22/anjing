import sqlite3
import smtplib
import re
import time
import asyncio
from email.mime.text import MIMEText
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

DB_FILE = "config.db"

# === DATABASE ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('group_mode', 'disabled')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('owner_id', '')")
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS premium (
            user_id INTEGER PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER,
            timestamp REAL,
            PRIMARY KEY (user_id, timestamp)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            title TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_config(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_config(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    owner_id = get_config("owner_id")
    if not owner_id:
        return False
    if str(user_id) == owner_id:
        return True
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def is_premium(user_id):
    owner_id = get_config("owner_id")
    if str(user_id) == owner_id:
        return True
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM premium WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_premium(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO premium (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def add_admin(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def record_usage(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = time.time()
    c.execute("INSERT INTO usage (user_id, timestamp) VALUES (?, ?)", (user_id, now))
    conn.commit()
    conn.close()

def get_usage_count(user_id, window_hours=1):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = time.time() - (window_hours * 3600)
    c.execute("SELECT COUNT(*) FROM usage WHERE user_id = ? AND timestamp > ?", (user_id, cutoff))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_next_reset_time(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT timestamp FROM usage 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 5
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    
    if len(rows) < 5:
        return None
    
    fifth_time = rows[-1][0]
    next_reset = fifth_time + 3600
    return next_reset if next_reset > time.time() else None

def add_group(chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def is_group_allowed(chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM groups WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_chat(chat_id, chat_type, title=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO active_chats (chat_id, chat_type, title) VALUES (?, ?, ?)",
              (chat_id, chat_type, title))
    conn.commit()
    conn.close()

# === EMAIL ===
def kirim_email_nomor_saja(nomor_final: str, email_from: str, email_password: str):
    body = f"+{nomor_final}"
    msg = MIMEText(body)
    msg['Subject'] = ""
    msg['From'] = email_from
    msg['To'] = "support@support.whatsapp.com"

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(email_from, email_password)
            server.sendmail(email_from, "support@support.whatsapp.com", msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = get_config("owner_id")
    if not owner_id:
        await update.message.reply_text("🔐 Bot belum dikonfigurasi.\nKirim: /setowner [ID_ANDA]")
        return

    user_id = update.effective_user.id
    is_owner = (str(user_id) == owner_id)
    is_adm = is_admin(user_id)

    chat = update.effective_chat
    save_chat(chat.id, chat.type, getattr(chat, 'title', ''))

    if is_adm and not is_owner:
        await update.message.reply_text("👥 ADMIN COMMAND")
        return

    if is_owner:
        keyboard = [
            [InlineKeyboardButton("👑 OWNER", callback_data="menu_owner")],
            [InlineKeyboardButton("👥 ADMIN", callback_data="menu_admin")],
            [InlineKeyboardButton("👨‍💻 Developer", url=f"tg://user?id={owner_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🔐 Selamat datang, Owner!", reply_markup=reply_markup)
        return

    pesan_bantuan = (
        "👋 Halo! Ini adalah bot banding WhatsApp.\n\n"
        "✅ **Cara Pakai**:\n"
        "Kirim perintah:\n"
        "   <code>/banding [nomor]</code>\n\n"
        "📝 **Format Nomor**:\n"
        "• Gunakan kode negara (tanpa +)\n"
        "• Contoh Indonesia: <code>6281234567890</code>\n"
        "• Contoh AS: <code>14155552671</code>\n\n"
        "ℹ️ Bot akan kirim nomor ke WhatsApp dalam format: <code>+6281234567890</code>"
    )

    keyboard = [[InlineKeyboardButton("👨‍💻 Developer", url=f"tg://user?id={owner_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(pesan_bantuan, reply_markup=reply_markup, parse_mode="HTML")

# === PERINTAH KRITIS: /setowner (BISA DIAKSES TANPA OWNER) ===
async def setowner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_owner = get_config("owner_id")
    if current_owner:
        await update.message.reply_text(f"❌ Owner sudah di-set: {current_owner}")
        return

    if not context.args:
        await update.message.reply_text("❌ Gunakan: /setowner [ID]\nContoh: /setowner 1628082131")
        return

    try:
        owner_id = str(int(context.args[0]))
    except ValueError:
        await update.message.reply_text("❌ ID harus angka!")
        return

    set_config("owner_id", owner_id)
    await update.message.reply_text(f"✅ Owner ID disetel ke: {owner_id}\n\nKirim /start untuk akses menu.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya admin yang bisa lihat bantuan.")
        return
    await update.message.reply_text("Gunakan /start untuk akses menu.")

# --- Menu Callbacks ---
async def menu_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if str(query.from_user.id) != get_config("owner_id"):
        await query.edit_message_text("❌ Akses ditolak.")
        return

    keyboard = [
        [InlineKeyboardButton("📧 Set Email", callback_data="owner_setemail")],
        [InlineKeyboardButton("🔑 Set Password", callback_data="owner_setpass")],
        [InlineKeyboardButton("➕ Add Admin", callback_data="owner_addadmin")],
        [InlineKeyboardButton("🌟 Add Premium", callback_data="owner_addpremium")],
        [InlineKeyboardButton("📊 Stats", callback_data="owner_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("👑 **Panel Owner**", reply_markup=reply_markup, parse_mode="Markdown")

async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return

    keyboard = [
        [InlineKeyboardButton("🔄 Set Mode Grup", callback_data="admin_setmode")],
        [InlineKeyboardButton("➕ Add Grup Ini", callback_data="admin_addgrup")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("👥 **Panel Admin**", reply_markup=reply_markup, parse_mode="Markdown")

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(query, context)

# --- Owner Actions (via button) ---
async def owner_setemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "setemail"
    await query.edit_message_text("📧 Kirim email pengirim (misal: cs@gmail.com):")

async def owner_setpass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "setpass"
    await query.edit_message_text("🔑 Kirim App Password email:")

async def owner_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "addadmin"
    await query.edit_message_text("➕ Kirim ID Telegram admin:")

async def owner_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "addpremium"
    await query.edit_message_text("🌟 Kirim ID Telegram user premium:")

async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM usage")
    total_banding = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM premium")
    total_premium = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM admins")
    total_admin = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM groups")
    total_grup = c.fetchone()[0]
    conn.close()
    pesan = (
        "📊 **Statistik Bot**\n\n"
        f"• Total Banding: `{total_banding}`\n"
        f"• User Premium: `{total_premium}`\n"
        f"• Admin: `{total_admin}`\n"
        f"• Grup Aktif: `{total_grup}`\n"
    )
    await query.edit_message_text(pesan, parse_mode="Markdown")

async def owner_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "broadcast"
    await query.edit_message_text("📢 Kirim pesan broadcast:")

# --- Admin Actions (via button) ---
async def admin_setmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = get_config("group_mode") or "disabled"
    status = "✅ Aktif" if current == "enable" else "❌ Nonaktif"
    keyboard = [
        [InlineKeyboardButton("✅ Enable", callback_data="setmode_enable")],
        [InlineKeyboardButton("❌ Disable", callback_data="setmode_disable")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"🔄 Pengaturan Mode Grup\nStatus saat ini: {status}\n\nPilih mode:",
        reply_markup=reply_markup
    )

async def admin_addgrup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat = query.message.chat
    if chat.type == "private":
        await query.edit_message_text("❌ Hanya bisa di grup!")
        return
    add_group(chat.id)
    await query.edit_message_text("✅ Grup ini diizinkan!")

# --- Setmode Button Handler ---
async def set_mode_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Akses ditolak.")
        return
    data = query.data
    if data == "setmode_enable":
        set_config("group_mode", "enable")
        await query.edit_message_text("✅ Mode grup diaktifkan!\nBot bisa dipakai di semua grup.")
    elif data == "setmode_disable":
        set_config("group_mode", "disable")
        await query.edit_message_text(
            "❌ Mode grup dinonaktifkan!\n"
            "Bot hanya aktif di:\n"
            "• Chat pribadi\n"
            "• Grup yang sudah di-`/addgrup`"
        )

# --- Text Handler for Owner Actions ---
async def handle_owner_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != get_config("owner_id"):
        return

    action = context.user_data.get("action")
    text = update.message.text.strip()

    if action == "setemail":
        if "@" not in text:
            await update.message.reply_text("❌ Format email tidak valid!")
            return
        set_config("email_from", text)
        await update.message.reply_text(f"✅ Email disetel ke: {text}")
    elif action == "setpass":
        set_config("email_password", text)
        await update.message.reply_text("✅ App Password disetel!")
    elif action == "addadmin":
        try:
            aid = int(text)
            add_admin(aid)
            await update.message.reply_text(f"✅ Admin ditambahkan: {aid}")
        except:
            await update.message.reply_text("❌ ID harus angka!")
    elif action == "addpremium":
        try:
            pid = int(text)
            add_premium(pid)
            await update.message.reply_text(f"🌟 Premium ditambahkan: {pid}")
        except:
            await update.message.reply_text("❌ ID harus angka!")
    elif action == "broadcast":
        pesan = "📣 **PENGUMUMAN**\n\n" + text
        owner_id = get_config("owner_id")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins")
        admins = [row[0] for row in c.fetchall()]
        c.execute("SELECT user_id FROM premium")
        premiums = [row[0] for row in c.fetchall()]
        conn.close()
        penerima = list(set(admins + premiums + [int(owner_id)]))
        sukses = 0
        for uid in penerima:
            try:
                await context.bot.send_message(chat_id=uid, text=pesan, parse_mode="Markdown")
                sukses += 1
            except:
                pass
        await update.message.reply_text(f"✅ Broadcast selesai! Terkirim ke {sukses} user.")
    
    context.user_data.pop("action", None)

# --- Banding ---
async def banding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    save_chat(chat.id, chat.type, getattr(chat, 'title', ''))

    if not is_admin(user_id):
        await update.message.reply_text("❌ Anda tidak diizinkan.")
        return

    group_mode = get_config("group_mode")
    is_grup_diizinkan = is_group_allowed(chat.id)
    if chat.type != "private":
        if group_mode != "enable" and not is_grup_diizinkan:
            await update.message.reply_text("❌ Bot tidak aktif di grup ini.")
            return

    email_from = get_config("email_from")
    email_password = get_config("email_password")
    if not email_from or not email_password:
        await update.message.reply_text("❌ Email belum disetel!")
        return

    if not context.args:
        await update.message.reply_text("❌ /banding [nomor]")
        return

    if not is_premium(user_id):
        count = get_usage_count(user_id, 1)
        if count >= 5:
            next_reset = get_next_reset_time(user_id)
            if next_reset:
                remaining = int(next_reset - time.time())
                if remaining > 0:
                    menit = remaining // 60
                    detik = remaining % 60
                    msg = await update.message.reply_text(
                        f"⏳ Tunggu **{menit} menit {detik} detik** sebelum bisa kirim lagi.",
                        parse_mode="Markdown"
                    )
                    for i in range(remaining):
                        await asyncio.sleep(1)
                        new_remaining = remaining - i - 1
                        if new_remaining <= 0:
                            break
                        new_menit = new_remaining // 60
                        new_detik = new_remaining % 60
                        try:
                            await msg.edit_text(
                                f"⏳ Tunggu **{new_menit} menit {new_detik} detik** sebelum bisa kirim lagi.",
                                parse_mode="Markdown"
                            )
                        except:
                            break
                    return

    nomor_input = context.args[0].strip()
    nomor_bersih = re.sub(r'[^\d]', '', nomor_input)

    if len(nomor_bersih) == 11 and nomor_bersih.startswith("0"):
        nomor_final = "62" + nomor_bersih[1:]
    else:
        nomor_final = nomor_bersih

    if len(nomor_final) < 8 or len(nomor_final) > 15:
        await update.message.reply_text("❌ Nomor harus 8–15 digit.")
        return

    success, error = kirim_email_nomor_saja(nomor_final, email_from, email_password)
    if success:
        if not is_premium(user_id):
            record_usage(user_id)
            count = get_usage_count(user_id, 1)
            await update.message.reply_text(
                f"✅ Terkirim: `+{nomor_final}`\n📊 Limit: {count}/5",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"✅ Terkirim: `+{nomor_final}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Gagal: {error}")

# === MAIN ===
if __name__ == "__main__":
    init_db()
    print("🔑 Masukkan BOT TOKEN dari @BotFather:")
    token = input().strip()

    app = Application.builder().token(token).build()

    # Handlers (urutan penting!)
    app.add_handler(CommandHandler("setowner", setowner))  # 👈 HARUS DI ATAS!
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("banding", banding))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_owner_input))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(menu_owner, pattern="^menu_owner$"))
    app.add_handler(CallbackQueryHandler(menu_admin, pattern="^menu_admin$"))
    app.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start$"))
    app.add_handler(CallbackQueryHandler(owner_setemail, pattern="^owner_setemail$"))
    app.add_handler(CallbackQueryHandler(owner_setpass, pattern="^owner_setpass$"))
    app.add_handler(CallbackQueryHandler(owner_addadmin, pattern="^owner_addadmin$"))
    app.add_handler(CallbackQueryHandler(owner_addpremium, pattern="^owner_addpremium$"))
    app.add_handler(CallbackQueryHandler(owner_stats, pattern="^owner_stats$"))
    app.add_handler(CallbackQueryHandler(owner_broadcast, pattern="^owner_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_setmode, pattern="^admin_setmode$"))
    app.add_handler(CallbackQueryHandler(admin_addgrup, pattern="^admin_addgrup$"))
    app.add_handler(CallbackQueryHandler(set_mode_button, pattern="^setmode_(enable|disable)$"))

    print("\n🚀 Bot aktif!")
    print("💡 Pertama kali? Kirim ke bot Anda:")
    print("   /setowner 1628082131")
    app.run_polling()