import asyncio
import logging
import os
import random
import string
import datetime
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS
import threading

# ================== НАЛАШТУВАННЯ ==================
BOT_TOKEN = "8464882605:AAGFAYMmgytLzSdzYWobSnrdT5uYf1YfOKw"
CHANNEL_USERNAME = "@feikDiq"
CHANNEL_ID = -1001234567890
ADMIN_ID = 7760606749
PWA_URL = "https://твой-railway-url.up.railway.app"  # Обнови после deploy
RULES_URL = "https://telegra.ph/твоє_посилання_на_правила"
INSTRUCTION_URL = "https://telegra.ph/твоє_посилання_на_інструкцію_оплати"
SUPPORT_USERNAME = "@твій_підтримка"
DB_FILE = "users.db"
PHOTOS_DIR = "photos"
RECEIPTS_DIR = "receipts"
STATIC_DIR = "static"  # Папка для PWA файлов (index.html, manifest.json, sw.js, иконки)

os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(RECEIPTS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Flask для API и PWA статики
flask_app = Flask(__name__, static_folder=STATIC_DIR)
CORS(flask_app)

@flask_app.route("/photos/<filename>")
def photos(filename):
    return send_from_directory(PHOTOS_DIR, filename)

@flask_app.route("/get_data")
async def get_data():
    code = request.args.get("code")
    if not code:
        return jsonify({"fio": "Невірний код", "birthdate": "", "photo_url": ""})

    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT fio, birthdate, photo_path, expiry_time, active FROM users WHERE code=?", (code,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return jsonify({"fio": "Невірний код або термін дії закінчився", "birthdate": "", "photo_url": ""})

            fio, birthdate, photo_path, expiry, active = row

            if active == 0 or (expiry and datetime.datetime.now().timestamp() > expiry):
                return jsonify({"fio": "ПЕРІОД ПОДПИСКИ ЗАВЕРШЕНО", "birthdate": "", "photo_url": ""})

            photo_url = f"/photos/{os.path.basename(photo_path)}" if photo_path else ""
            return jsonify({"fio": fio, "birthdate": birthdate, "photo_url": photo_url})

# Статические файлы PWA (index.html, manifest.json, sw.js, иконки)
@flask_app.route("/", defaults={"path": ""})
@flask_app.route("/<path:path>")
def serve_static(path):
    if path != "" and os.path.exists(os.path.join(STATIC_DIR, path)):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")

def run_flask():
    flask_app.run(host="0.0.0.0", port=8000)

# Бот
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

# ================== ІНІЦІАЛІЗАЦІЯ БД ==================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                fio TEXT,
                birthdate TEXT,
                photo_path TEXT,
                code TEXT,
                subscription_type TEXT,
                expiry_time REAL,
                active INTEGER DEFAULT 1
            )
        ''')
        await db.commit()

# ================== СТАНИ ==================
class States(StatesGroup):
    subscribed_check = State()
    fio = State()
    birthdate = State()
    photo = State()
    choose_subscription = State()
    payment_method = State()
    waiting_card = State()
    waiting_receipt = State()

# ================== ДОПОМІЖНІ ФУНКЦІЇ ==================
def generate_code():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

async def send_code_message(user_id: int, sub_type: str = "test"):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT code FROM users WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            code = row[0] if row else generate_code()
    text = (
        f"🎉 Ваша {'тестова ' if sub_type == 'test' else ''}підписка активна{' на 30 хвилин' if sub_type == 'test' else ''}!\n\n"
        f"🔑 Код для входу: {code}\n\n"
        f"🌐 Щоб увійти, перейдіть за посиланням:\n{PWA_URL}\n\n"
        "❗️ Не відкривайте посилання в Telegram\n"
        "❗️ Скопіюйте його та відкрийте у браузері\n\n"
        "Дякуємо, що скористалися нашим сервісом!"
    )
    await bot.send_message(user_id, text)

# ================== /start ==================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Погодитися з правилами", callback_data="agree_rules")]
    ])
    text = (
        "Вітаємо! 🤖\n\n"
        "Щоб розпочати роботу з ботом, будь ласка, ознайомтеся та погодьтеся з правилами користування:\n\n"
        f"📄 {RULES_URL}\n\n"
        "⛔️ До підтвердження згоди бот не зможе відповідати на повідомлення."
    )
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)

# ================== Згода з правилами ==================
@dp.callback_query(lambda c: c.data == "agree_rules")
async def agree_rules(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Підписатися на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
        [InlineKeyboardButton(text="✅ Перевірити підписку", callback_data="check_sub")]
    ])
    text = (
        "🌟 Для подальшого користування ботом необхідно підписатися на наш канал\n\n"
        f"📢 У каналі {CHANNEL_USERNAME} ви знайдете свіжі новини, оновлення та корисні матеріали\n\n"
        "⏱ Підписка займає лише кілька секунд, зате відкриває повний доступ до можливостей бота 😊\n\n"
        "👇 Натисніть кнопку нижче, підпишіться на канал і підтвердьте підписку"
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
    await state.set_state(States.subscribed_check)

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub(callback: CallbackQuery, state: FSMContext):
    text = (
        "📝 Настав час заповнити ваші дані\n\n"
        "Будь ласка, надішліть ваше ПІБ українською мовою, починаючи з великої літери\n"
        "✨ Приклад оформлення:\nІваненко Олексій Сергійович\n\n"
        "Дякуємо за уважність та коректне заповнення 😊"
    )
    await callback.message.edit_text(text)
    await state.set_state(States.fio)
    await callback.answer()

# ================== Збір даних ==================
@dp.message(States.fio)
async def process_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    text = (
        "📅 Чудово! Тепер, будь ласка, вкажіть вашу дату народження\n"
        "✍️ Напишіть її у форматі ДД.ММ.РРРР\n"
        "✨ Приклад: 29.07.2005\n"
        "❗️ Зверніть увагу на крапки — формат має значення 😉🎂"
    )
    await message.answer(text)
    await state.set_state(States.birthdate)

@dp.message(States.birthdate)
async def process_birthdate(message: Message, state: FSMContext):
    try:
        datetime.datetime.strptime(message.text, "%d.%m.%Y")
        await state.update_data(birthdate=message.text)
        text = (
            "📸 Час додати ваше фото\n"
            "Будь ласка, надішліть фотографію у форматі 3×4\n"
            "💡 Щоб фото підійшло без проблем:\n"
            "• Оберіть чітке та якісне зображення\n"
            "• Переконайтеся, що пропорції відповідають формату\n"
            "• Обличчя має бути добре видно — без масок, сонцезахисних окулярів і сторонніх об’єктів на фоні 😉\n\n"
            "Заздалегідь дякуємо за ваше чудове фото! 😊"
        )
        await message.answer(text)
        await state.set_state(States.photo)
    except:
        await message.answer("❗️ Неправильний формат дати. Спробуйте ще раз.")

@dp.message(States.photo, lambda m: m.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    code = generate_code()
    photo_file = message.photo[-1]
    photo_path = f"{PHOTOS_DIR}/{user_id}.jpg"
    await bot.download(photo_file, photo_path)
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, fio, birthdate, photo_path, code) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, data['fio'], data['birthdate'], photo_path, code)
        )
        await db.commit()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 3 місяці — 165 грн", callback_data="sub_3m")],
        [InlineKeyboardButton(text="💍 6 місяців — 240 грн", callback_data="sub_6m")],
        [InlineKeyboardButton(text="👑 Безстрокова — 400 грн", callback_data="sub_unlim")],
        [InlineKeyboardButton(text="⏳ Тестовий доступ на 30 хвилин - 0 грн", callback_data="sub_test")]
    ])
    text = (
        "💰 Вартість підписки:\n"
        "🔹 3 місяці — 165 грн 💳\n"
        "🔹 6 місяців — 240 грн 💎\n"
        "🔹 Безстрокова — 400 грн 🔥\n\n"
        "⏳ Тестовий доступ на 30 хвилин — безкоштовно 🎉\n\n"
        "❓ Якщо виникнуть запитання — сміливо звертайтеся, ми завжди раді допомогти 😊🤝\n"
        "🙏 Просимо: якщо ви плануєте оформити підписку, спершу активуйте тестовий доступ, щоб ознайомитися з можливостями сервісу 🥺"
    )
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(States.choose_subscription)

# ================== Вибір підписки ==================
@dp.callback_query(lambda c: c.data and c.data.startswith("sub_"))
async def choose_subscription(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    sub_type = callback.data
    if sub_type == "sub_test":
        expiry = datetime.datetime.now().timestamp() + 1800
        new_code = generate_code()
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE users SET code=?, subscription_type='test', expiry_time=?, active=1 WHERE user_id=?", (new_code, expiry, user_id))
            await db.commit()
        await send_code_message(user_id, "test")
        await callback.message.edit_text("🎉 Тестовий доступ активовано на 30 хвилин! Код надіслано в чат.")
        await callback.answer()
        return
    prices = {"sub_3m": 165, "sub_6m": 240, "sub_unlim": 400}
    names = {"sub_3m": "3 місяці", "sub_6m": "6 місяців", "sub_unlim": "Безстрокова"}
    price = prices[sub_type]
    name = names[sub_type]
    await state.update_data(selected_sub=name, selected_price=price)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 CryptoBot", callback_data="pay_crypto")],
        [InlineKeyboardButton(text="💰 Переказ на картку", callback_data="pay_card")],
        [InlineKeyboardButton(text="🔙 Повернутися назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text("💳 Як вам буде зручно оплатити?", reply_markup=keyboard)
    await state.set_state(States.payment_method)
    await callback.answer()

# ================== Назад до меню підписки ==================
@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 3 місяці — 165 грн", callback_data="sub_3m")],
        [InlineKeyboardButton(text="💍 6 місяців — 240 грн", callback_data="sub_6m")],
        [InlineKeyboardButton(text="👑 Безстрокова — 400 грн", callback_data="sub_unlim")],
        [InlineKeyboardButton(text="⏳ Тестовий доступ на 30 хвилин - 0 грн", callback_data="sub_test")]
    ])
    text = "Оберіть тип підписки ще раз:"
    await callback.message.edit_text(text, reply_markup=keyboard)
    await state.set_state(States.choose_subscription)

# ================== CryptoBot оплата ==================
@dp.callback_query(lambda c: c.data == "pay_crypto")
async def pay_crypto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sum_to_pay = data['selected_price'] + 20
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Перейти до оплати", url="https://t.me/CryptoBot?start=pay")],
        [InlineKeyboardButton(text="📖 Інструкція", url=INSTRUCTION_URL)],
        [InlineKeyboardButton(text="🆘 Підтримка", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
        [InlineKeyboardButton(text="🔍 Перевірити оплату", callback_data="check_crypto")],
        [InlineKeyboardButton(text="🔙 Повернутися назад", callback_data="back_payment")]
    ])
    text = (
        "💳 Оплата через CryptoBot\n\n"
        f"💲 Сума до сплати: {sum_to_pay}₴\n"
        "⏳ Термін дії інвойса: залишилось 59 хвилин\n"
        "📚 Інструкцію можна переглянути за кнопкою нижче\n"
        "❗️ Увага: підписка буде активована автоматично після оплати"
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Підключити підписку", callback_data=f"approve_crypto_{callback.from_user.id}")],
    ])
    await bot.send_message(ADMIN_ID, f"Користувач {callback.from_user.id} перейшов до оплати CryptoBot на {data['selected_sub']}. Підтвердити?", reply_markup=admin_keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("approve_crypto_"))
async def approve_crypto(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    new_code = generate_code()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET code=?, subscription_type='paid', active=1, expiry_time=NULL WHERE user_id=?", (new_code, user_id))
        await db.commit()
    await send_code_message(user_id, "paid")
    await bot.send_message(user_id, "✅ Ваша підписка активована!")
    await callback.answer("Підписку підключено")

# ================== КОМАНДА ДЛЯ АДМІНА: обнулити акаунт ==================
@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("Формат: /reset USER_ID")
            return
        target_user_id = int(parts[1])
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target_user_id,))
            await db.commit()
        await message.answer(f"✅ Акаунт користувача {target_user_id} обнулено!\nТепер він може пройти реєстрацію і взяти тестовий доступ заново.")
        try:
            await bot.send_message(target_user_id, "🔄 Ваш акаунт обнулено адміністратором. Тепер ви можете пройти реєстрацію заново (/start).")
        except:
            pass
    except ValueError:
        await message.answer("Неправильний формат USER_ID (має бути число)")
    except Exception as e:
        await message.answer(f"Помилка: {e}")

# ================== ЗАПУСК ==================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
