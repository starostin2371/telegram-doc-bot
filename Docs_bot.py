from PIL import Image
import pytesseract
from telegram import Update, Document, PhotoSize, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from telegram.constants import ChatType
import logging
import os
import re
from openai import OpenAI

# Настройки путей
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Ключи
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Логгирование
logging.basicConfig(level=logging.INFO)

# Хранилище состояний
user_state = {}
user_files = {}

# Главное меню
main_menu = ReplyKeyboardMarkup([["Сохранить весь текст", "Найти данные"]], one_time_keyboard=True, resize_keyboard=True)

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_input = update.message.text.lower()

    if user_input in ["привет", "ты кто"]:
        intro = (
            "Привет! Я — ассистент, который умеет:\n"
            "• Отвечать на любые вопросы\n"
            "• Обрабатывать документы и вытаскивать из них нужные данные\n"
            "• Распознавать текст на сканах и фото\n\n"
            "Просто отправь мне файл 📄"
        )
        await update.message.reply_text(intro)
        return

    if user_id in user_state:
        if user_state[user_id] == "awaiting_action":
            if user_input == "сохранить весь текст":
                file_path = user_files[user_id]
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                await update.message.reply_text(text[:4000])
                user_state.pop(user_id)
                user_files.pop(user_id)
            elif user_input == "найти данные":
                user_state[user_id] = "awaiting_fields"
                await update.message.reply_text("Какие данные нужно найти? Например: email, телефон, ссылки")
            else:
                await update.message.reply_text("Выберите действие из меню.")
        elif user_state[user_id] == "awaiting_fields":
            file_path = user_files[user_id]
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            response = extract_data(text, user_input)
            await update.message.reply_text(response[:4000])
            user_state.pop(user_id)
            user_files.pop(user_id)
        return

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": user_input}]
        )
        answer = response.choices[0].message.content
    except Exception as e:
        answer = f"Ошибка OpenAI: {e}"
    await update.message.reply_text(answer)

# Обработка документов
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    document: Document = update.message.document
    file = await document.get_file()
    file_path = f"{document.file_unique_id}_{document.file_name}"
    await file.download_to_drive(file_path)

    extracted_text = ""

    try:
        if file_path.endswith(".txt"):
            with open(file_path, "r", encoding="utf-8") as f:
                extracted_text = f.read()
        elif file_path.endswith(".docx"):
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            extracted_text = "\n".join([p.text for p in doc.paragraphs])
        elif file_path.endswith(".pdf"):
            import fitz
            doc = fitz.open(file_path)
            for page in doc:
                extracted_text += page.get_text()
            doc.close()
        elif file_path.lower().endswith((".jpg", ".jpeg", ".png")):
            extracted_text = pytesseract.image_to_string(Image.open(file_path), lang="rus+eng")
        else:
            extracted_text = "Формат не поддерживается."
    except Exception as e:
        extracted_text = f"Ошибка при извлечении текста: {e}"

    temp_path = f"extracted_{user_id}.txt"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(extracted_text)

    user_state[user_id] = "awaiting_action"
    user_files[user_id] = temp_path

    await update.message.reply_text("Что вы хотите сделать с документом?", reply_markup=main_menu)

# Обработка изображений
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo: PhotoSize = update.message.photo[-1]
    file = await photo.get_file()
    file_path = f"{photo.file_unique_id}.jpg"
    await file.download_to_drive(file_path)

    try:
        text = pytesseract.image_to_string(Image.open(file_path), lang="rus+eng")
        await update.message.reply_text(f"Распознанный текст:\n\n{text[:4000]}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при распознавании: {e}")
    finally:
        try:
            os.remove(file_path)
        except:
            pass

# Извлечение данных по шаблонам
def extract_data(text, fields):
    result = []
    if "email" in fields:
        emails = re.findall(r"[\w\.-]+@[\w\.-]+", text)
        result.append("Email:\n" + "\n".join(set(emails)))
    if "телефон" in fields or "phone" in fields:
        phones = re.findall(r"(\+?\d[\d\s\-()]{7,}\d)", text)
        result.append("Телефоны:\n" + "\n".join(set(phones)))
    if "ссылк" in fields or "http" in fields or "url" in fields:
        links = re.findall(r"https?://[\w\.-/]+|www\.[\w\.-]+", text)
        result.append("Ссылки:\n" + "\n".join(set(links)))
    if not result:
        return "Ничего не найдено по заданным критериям."
    return "\n\n".join(result)

# Запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Бот запущен")
    app.run_polling()
