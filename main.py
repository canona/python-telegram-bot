import base64
import io
import logging
import os
import sys
import time

import telebot
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("antigravity-telegram-bot")


def load_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical("Thiếu biến môi trường bắt buộc: %s", name)
        sys.exit(1)
    return value


TELEGRAM_BOT_TOKEN = load_required_env("TELEGRAM_BOT_TOKEN")
ANTIGRAVITY_API_BASE = load_required_env("ANTIGRAVITY_API_BASE")
ANTIGRAVITY_API_KEY = load_required_env("ANTIGRAVITY_API_KEY")
AI_MODEL_NAME = load_required_env("AI_MODEL_NAME")

MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Bạn là một trợ lý AI hữu ích, trả lời ngắn gọn và chính xác.",
)
AVAILABLE_MODELS = [
    model.strip()
    for model in os.getenv("AVAILABLE_MODELS", AI_MODEL_NAME).split(",")
    if model.strip()
]

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode=None)

ai_client = OpenAI(
    base_url=ANTIGRAVITY_API_BASE,
    api_key=ANTIGRAVITY_API_KEY,
)

conversation_store: dict[int, list[dict[str, str]]] = {}
selected_model_store: dict[int, str] = {}


def get_history(chat_id: int) -> list[dict[str, str]]:
    if chat_id not in conversation_store:
        conversation_store[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return conversation_store[chat_id]


def trim_history(chat_id: int) -> None:
    history = conversation_store[chat_id]
    if len(history) > MAX_HISTORY_MESSAGES + 1:
        conversation_store[chat_id] = [history[0]] + history[-MAX_HISTORY_MESSAGES:]


def get_selected_model(chat_id: int) -> str:
    return selected_model_store.get(chat_id, AI_MODEL_NAME)


def is_image_model(model_id: str) -> bool:
    return "image" in model_id.lower()


def describe_error(error: Exception, chat_id: int) -> str:
    if isinstance(error, AuthenticationError):
        logger.error("Lỗi xác thực với Antigravity Manager (API key không hợp lệ).")
        return "Xin lỗi, hệ thống xác thực AI đang gặp sự cố. Vui lòng liên hệ quản trị viên."

    if isinstance(error, RateLimitError):
        logger.error("Đã vượt hạn mức (quota) hoặc rate limit của Antigravity Manager.")
        return "Xin lỗi, hệ thống AI hiện đã hết hạn mức sử dụng. Vui lòng thử lại sau ít phút."

    if isinstance(error, (APIConnectionError, APITimeoutError)):
        logger.error("Mất kết nối tới Antigravity Manager tại %s", ANTIGRAVITY_API_BASE)
        return "Xin lỗi, không thể kết nối tới máy chủ AI lúc này. Vui lòng thử lại sau."

    if isinstance(error, APIStatusError):
        logger.error("Antigravity Manager trả về lỗi HTTP %s: %s", error.status_code, error.message)
        return "Xin lỗi, máy chủ AI phản hồi lỗi. Vui lòng thử lại sau."

    logger.exception("Lỗi không xác định khi xử lý yêu cầu từ chat_id=%s", chat_id)
    return "Xin lỗi, đã xảy ra lỗi không mong muốn. Vui lòng thử lại sau."


@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message) -> None:
    conversation_store.pop(message.chat.id, None)
    bot.reply_to(
        message,
        "Xin chào! Tôi là bot AI kết nối qua Antigravity Manager.\n"
        "Gửi tin nhắn bất kỳ để bắt đầu trò chuyện.\n"
        "Dùng /model để chọn model AI (kể cả model tạo ảnh).\n"
        "Dùng /reset để xóa lịch sử hội thoại hiện tại.",
    )


@bot.message_handler(commands=["reset"])
def handle_reset(message: telebot.types.Message) -> None:
    conversation_store.pop(message.chat.id, None)
    bot.reply_to(message, "Đã xóa lịch sử hội thoại. Bắt đầu cuộc trò chuyện mới.")


@bot.message_handler(commands=["model"])
def handle_model_command(message: telebot.types.Message) -> None:
    chat_id = message.chat.id
    current_model = get_selected_model(chat_id)

    markup = telebot.types.InlineKeyboardMarkup()
    for model_id in AVAILABLE_MODELS:
        label = f"✅ {model_id}" if model_id == current_model else model_id
        markup.add(telebot.types.InlineKeyboardButton(label, callback_data=f"model:{model_id}"))

    bot.send_message(
        chat_id,
        f"Model đang dùng: {current_model}\nChọn model bạn muốn sử dụng:",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("model:"))
def handle_model_selection(call: telebot.types.CallbackQuery) -> None:
    chat_id = call.message.chat.id
    model_id = call.data.split("model:", 1)[1]
    selected_model_store[chat_id] = model_id
    bot.answer_callback_query(call.id, f"Đã chọn model: {model_id}")
    bot.edit_message_text(
        f"Đã chuyển sang model: {model_id}",
        chat_id=chat_id,
        message_id=call.message.message_id,
    )


def handle_image_request(message: telebot.types.Message, model_id: str) -> None:
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, "upload_photo")

    try:
        response = ai_client.images.generate(
            model=model_id,
            prompt=message.text,
            n=1,
            response_format="b64_json",
        )
        image_bytes = base64.b64decode(response.data[0].b64_json)
        bot.send_photo(chat_id, photo=io.BytesIO(image_bytes), caption=f"Model: {model_id}")

    except Exception as error:
        bot.reply_to(message, describe_error(error, chat_id))


@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    chat_id = message.chat.id
    model_id = get_selected_model(chat_id)

    if is_image_model(model_id):
        handle_image_request(message, model_id)
        return

    history = get_history(chat_id)
    history.append({"role": "user", "content": message.text})

    bot.send_chat_action(chat_id, "typing")

    try:
        response = ai_client.chat.completions.create(
            model=model_id,
            messages=history,
        )
        reply_text = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply_text})
        trim_history(chat_id)
        bot.reply_to(message, reply_text)

    except Exception as error:
        bot.reply_to(message, describe_error(error, chat_id))
        history.pop()


def main() -> None:
    logger.info("Khởi động bot với model AI: %s", AI_MODEL_NAME)
    logger.info("Antigravity Manager endpoint: %s", ANTIGRAVITY_API_BASE)

    retry_delay_seconds = 5
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception:
            logger.exception(
                "Bot polling bị gián đoạn, thử kết nối lại sau %s giây.",
                retry_delay_seconds,
            )
            time.sleep(retry_delay_seconds)


if __name__ == "__main__":
    main()
