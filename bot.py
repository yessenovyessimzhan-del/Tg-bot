import os
import re
import requests
from requests import Session
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from youtube_transcript_api import YouTubeTranscriptApi


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

client = genai.Client(api_key=GEMINI_API_KEY)
user_languages = {}
user_sources = {}

def is_youtube_url(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def get_youtube_id(url: str) -> str | None:
    patterns = [
        r"v=([^&]+)",
        r"youtu\.be/([^?&]+)",
        r"shorts/([^?&]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def get_youtube_text(url: str) -> str:
    video_id = get_youtube_id(url)

    if not video_id:
        raise Exception("❌ Не удалось определить ID видео.")

    try:

        session = Session()

        with open("cookies.txt", "r", encoding="utf-8") as f:
            cookies_raw = f.read()

        for line in cookies_raw.splitlines():

            if line.startswith("#") or not line.strip():
                continue

            parts = line.split("\t")

            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]

                session.cookies.set(name, value)

        ytt_api = YouTubeTranscriptApi(http_client=session)

        transcript_list = ytt_api.list(video_id)

        transcript = None

        try:
            transcript = transcript_list.find_transcript(["ru", "en"])
        except:
            pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(
                    ["ru", "en"]
                )
            except:
                pass

        if transcript is None:
            raise Exception("Субтитры не найдены.")

        fetched = transcript.fetch()

        text = " ".join([item.text for item in fetched])

        if len(text) < 100:
            raise Exception("Слишком мало текста.")

        return text

    except Exception as e:
        raise Exception(
            f"❌ Не удалось получить субтитры.\n\n{e}"
        )
def get_article_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    paragraphs = soup.find_all("p")
    text = "\n".join(p.get_text(strip=True) for p in paragraphs)

    if len(text) < 300:
        text = soup.get_text(separator="\n", strip=True)

    return text[:30000]


def summarize_text(text: str, language: str = "russian") -> str:

    language_map = {
        "kazakh": "Қазақ тілінде жаз.",
        "russian": "Пиши на русском языке.",
        "english": "Write in English."
    }

    language_instruction = language_map.get(
        language,
        "Пиши на русском языке."
    )

    prompt = f"""
Ты — саммаризатор для Telegram-бота.

{language_instruction}

ВАЖНЫЕ ПРАВИЛА:
- НЕ используй Markdown
- НЕ используй **
- Пиши как красивый Telegram-пост
- Делай короткие абзацы
- Используй эмодзи умеренно
- Делай текст удобным для телефона

ФОРМАТ:

📌 Главная мысль

🧠 Краткая выжимка

🔑 Ключевые идеи

💡 Что важно запомнить

🛠 Практическая польза

Текст:
{text}
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    return response.text

def answer_question_from_source(source_text: str, question: str, language: str = "russian") -> str:

    language_map = {
        "kazakh": "Қазақ тілінде жауап бер.",
        "russian": "Отвечай на русском языке.",
        "english": "Answer in English."
    }

    language_instruction = language_map.get(
        language,
        "Отвечай на русском языке."
    )

    prompt = f"""
Ты отвечаешь на вопрос пользователя и можешь отклонятся с источника но предупреждай.

{language_instruction}

ВАЖНЫЕ ПРАВИЛА:
- Не используй Markdown.
- Пиши удобно для Telegram.
- Ответ должен быть понятным и не слишком длинным.

Источник:
{source_text}

Вопрос пользователя:
{question}
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    return response.text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Скинь мне ссылку на статью или YouTube-видео, а я сделаю краткую выжимку."
    )

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        ["🇰🇿 Қазақша"],
        ["🇷🇺 Русский"],
        ["🇬🇧 English"]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🌐 Выбери язык саммари:",
        reply_markup=reply_markup
    )

async def language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text == "🇰🇿 Қазақша":
        user_languages[update.effective_user.id] = "kazakh"

        await update.message.reply_text(
            "✅ Тіл қазақша болып орнатылды."
        )

    elif text == "🇷🇺 Русский":
        user_languages[update.effective_user.id] = "russian"

        await update.message.reply_text(
            "✅ Язык установлен: русский."
        )

    elif text == "🇬🇧 English":
        user_languages[update.effective_user.id] = "english"

        await update.message.reply_text(
            "✅ Language set to English."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()

    user_id = update.effective_user.id

    user_language = user_languages.get(
        user_id,
        "russian"
    )

    messages = {
        "kazakh": {
            "no_source": "🔗 Алдымен маған мақала немесе YouTube-видео сілтемесін жібер.",
            "start": "⏳ Контентті қарап, қысқаша мазмұн дайындап жатырмын...",
            "youtube": "🎥 YouTube субтитрлерін алып жатырмын...",
            "article": "📄 Мақаланы оқып жатырмын...",
            "not_enough": "❌ Жеткілікті мәтін ала алмадым.",
            "analyzing": "🧠 Материалды талдап жатырмын...",
            "saved": "✅ Дайын. Енді осы дереккөз бойынша сұрақ қоя аласың.",
            "answering": "💬 Сұрағыңа дереккөз бойынша жауап іздеп жатырмын...",
            "error": "❌ Қате:"
        },
        "russian": {
            "no_source": "🔗 Сначала пришли ссылку на статью или YouTube-видео.",
            "start": "⏳ Смотрю контент и делаю выжимку...",
            "youtube": "🎥 Получаю субтитры YouTube...",
            "article": "📄 Читаю статью...",
            "not_enough": "❌ Не удалось получить достаточно текста.",
            "analyzing": "🧠 Анализирую материал...",
            "saved": "✅ Готово. Теперь можешь задавать вопросы по этому источнику.",
            "answering": "💬 Ищу ответ в источнике...",
            "error": "❌ Ошибка:"
        },
        "english": {
            "no_source": "🔗 First, send me a link to an article or YouTube video.",
            "start": "⏳ Checking the content and preparing a summary...",
            "youtube": "🎥 Getting YouTube subtitles...",
            "article": "📄 Reading the article...",
            "not_enough": "❌ I could not extract enough text.",
            "analyzing": "🧠 Analyzing the material...",
            "saved": "✅ Done. Now you can ask questions about this source.",
            "answering": "💬 Looking for the answer in the source...",
            "error": "❌ Error:"
        }
    }

    t = messages.get(user_language, messages["russian"])

    url_match = re.search(r"https?://\S+", message)

    try:
        if url_match:
            url = url_match.group(0)

            await update.message.reply_text(t["start"])

            if is_youtube_url(url):
                await update.message.reply_text(t["youtube"])
                text = get_youtube_text(url)
            else:
                await update.message.reply_text(t["article"])
                text = get_article_text(url)

            if len(text) < 100:
                await update.message.reply_text(t["not_enough"])
                return

            user_sources[user_id] = text

            await update.message.reply_text(t["analyzing"])

            summary = summarize_text(text, user_language)

            MAX_LENGTH = 4000

            for i in range(0, len(summary), MAX_LENGTH):
                chunk = summary[i:i + MAX_LENGTH]
                await update.message.reply_text(chunk)

            await update.message.reply_text(t["saved"])
            return

        if user_id not in user_sources:
            await update.message.reply_text(t["no_source"])
            return

        await update.message.reply_text(t["answering"])

        answer = answer_question_from_source(
            user_sources[user_id],
            message,
            user_language
        )

        MAX_LENGTH = 4000

        for i in range(0, len(answer), MAX_LENGTH):
            chunk = answer[i:i + MAX_LENGTH]
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text(
            f"{t['error']}\n{e}"
        )

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("language", language_command))

    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("^(🇰🇿 Қазақша|🇷🇺 Русский|🇬🇧 English)$"),
            language_selection
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
