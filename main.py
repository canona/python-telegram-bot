import logging
import os
import sys
import time

import telebot
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

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

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode=None)

ai_client = OpenAI(
    base_url=ANTIGRAVITY_API_BASE,
    api_key=ANTIGRAVITY_API_KEY,
)

conversation_store: dict[int, list[dict[str, str]]] = {}


def get_history(chat_id: int) -> list[dict[str, str]]:
    if chat_id not in conversation_store:
        conversation_store[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return conversation_store[chat_id]


def trim_history(chat_id: int) -> None:
    history = conversation_store[chat_id]
    if len(history) > MAX_HISTORY_MESSAGES + 1:
        conversation_store[chat_id] = [history[0]] + history[-MAX_HISTORY_MESSAGES:]


@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message) -> None:
    conversation_store.pop(message.chat.id, None)
    bot.reply_to(
        message,
        "Xin chào! Tôi là bot AI kết nối qua Antigravity Manager.\n"
        "Gửi tin nhắn bất kỳ để bắt đầu trò chuyện.\n"
        "Dùng /reset để xóa lịch sử hội thoại hiện tại.",
    )


@bot.message_handler(commands=["reset"])
def handle_reset(message: telebot.types.Message) -> None:
    conversation_store.pop(message.chat.id, None)
    bot.reply_to(message, "Đã xóa lịch sử hội thoại. Bắt đầu cuộc trò chuyện mới.")


@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    chat_id = message.chat.id
    history = get_history(chat_id)
    history.append({"role": "user", "content": message.text})

    bot.send_chat_action(chat_id, "typing")

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL_NAME,
            messages=history,
        )
        reply_text = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply_text})
        trim_history(chat_id)
        bot.reply_to(message, reply_text)

    except AuthenticationError:
        logger.error("Lỗi xác thực với Antigravity Manager (API key không hợp lệ).")
        bot.reply_to(
            message,
            "Xin lỗi, hệ thống xác thực AI đang gặp sự cố. Vui lòng liên hệ quản trị viên.",
        )
        history.pop()

    except RateLimitError:
        logger.error("Đã vượt hạn mức (quota) hoặc rate limit của Antigravity Manager.")
        bot.reply_to(
            message,
            "Xin lỗi, hệ thống AI hiện đã hết hạn mức sử dụng. Vui lòng thử lại sau ít phút.",
        )
        history.pop()

    except (APIConnectionError, APITimeoutError):
        logger.error("Mất kết nối tới Antigravity Manager tại %s", ANTIGRAVITY_API_BASE)
        bot.reply_to(
            message,
            "Xin lỗi, không thể kết nối tới máy chủ AI lúc này. Vui lòng thử lại sau.",
        )
        history.pop()

    except APIStatusError as error:
        logger.error("Antigravity Manager trả về lỗi HTTP %s: %s", error.status_code, error.message)
        bot.reply_to(
            message,
            "Xin lỗi, máy chủ AI phản hồi lỗi. Vui lòng thử lại sau.",
        )
        history.pop()

    except Exception:
        logger.exception("Lỗi không xác định khi xử lý tin nhắn từ chat_id=%s", chat_id)
        bot.reply_to(
            message,
            "Xin lỗi, đã xảy ra lỗi không mong muốn. Vui lòng thử lại sau.",
        )
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
