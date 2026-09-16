# Telegram Bot AI qua Antigravity Manager

Bot Telegram kết nối tới các mô hình AI thông qua hệ thống quản lý API tập trung
**Antigravity Manager**, sử dụng chuẩn giao tiếp OpenAI-compatible API (thư viện `openai`).
Thiết kế để chạy 24/7 dưới dạng Background Service trên Coolify, đóng gói qua Docker,
CI/CD tự động qua GitHub Actions.

## Kiến trúc

```
.
├── main.py                      # Logic bot: nhận tin nhắn Telegram, gọi Antigravity Manager
├── requirements.txt              # pyTelegramBotAPI, openai, flake8
├── Dockerfile                    # Đóng gói ứng dụng, chạy python -u main.py
└── .github/workflows/deploy.yml  # Lint + trigger deploy webhook Coolify
```

## 1. Cấu hình biến môi trường trên Coolify

Vào project trên Coolify → tab **Environment Variables** → khai báo các biến sau:

| Biến môi trường          | Mô tả                                                                 | Ví dụ                                  |
|---------------------------|------------------------------------------------------------------------|------------------------------------------|
| `TELEGRAM_BOT_TOKEN`      | Token bot lấy từ [@BotFather](https://t.me/BotFather)                  | `123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `ANTIGRAVITY_API_BASE`    | Base URL endpoint OpenAI-compatible của Antigravity Manager             | `https://antigravity.example.com/v1`     |
| `ANTIGRAVITY_API_KEY`     | API Key do Antigravity Manager cấp                                     | `ag-xxxxxxxxxxxxxxxxxxxxxxxx`            |
| `AI_MODEL_NAME`           | Tên model AI được Antigravity Manager route đến (Gemini, GPT, Claude…) | `gemini-2.0-flash`                       |

Biến tùy chọn (có giá trị mặc định nếu bỏ trống):

| Biến môi trường         | Mặc định                                                    | Mô tả                                      |
|---------------------------|--------------------------------------------------------------|---------------------------------------------|
| `SYSTEM_PROMPT`           | `Bạn là một trợ lý AI hữu ích, trả lời ngắn gọn và chính xác.` | System prompt định hình vai trò của bot     |
| `MAX_HISTORY_MESSAGES`    | `20`                                                          | Số lượng tin nhắn giữ lại trong ngữ cảnh hội thoại |

### Lưu ý quan trọng: TẮT Healthcheck Port

Đây là bot chạy theo cơ chế **long-polling** (không mở port HTTP nào để lắng nghe request).
Coolify mặc định sẽ cố gắng healthcheck vào một port để xác nhận container "healthy" — với
loại ứng dụng này, healthcheck sẽ luôn thất bại và khiến Coolify liên tục restart container.

**Bắt buộc phải tắt Healthcheck**:

1. Vào project → tab **General** hoặc **Health Checks**.
2. Tắt (disable) **Healthcheck** / bỏ chọn **Is health check enabled**.
3. Đảm bảo **Ports Exposes** để trống (không expose port nào), vì bot không phục vụ HTTP.
4. Chọn chế độ chạy dịch vụ là **Background Worker / Application** (không phải Web Service cần port).

Nếu không tắt healthcheck, container sẽ bị đánh dấu unhealthy và bị kill liên tục dù bot
vẫn hoạt động bình thường bên trong.

## 2. Lấy Deploy Webhook URL từ Coolify và cấu hình GitHub Secrets

1. Trong Coolify, vào project của bot → tab **Webhooks**.
2. Copy giá trị **Deploy Webhook URL** (dạng
   `https://coolify.example.com/api/v1/deploy?uuid=xxxxxxxx&force=false`).
3. Sang GitHub repository → **Settings → Secrets and variables → Actions → New repository secret**.
4. Tạo secret với tên chính xác: `COOLIFY_WEBHOOK_URL`, giá trị là URL vừa copy ở bước 2.
5. Push code lên nhánh `main` — pipeline `.github/workflows/deploy.yml` sẽ tự động:
   - Chạy `flake8` kiểm tra lỗi cú pháp.
   - Nếu lint pass, gọi `curl` tới `COOLIFY_WEBHOOK_URL` để yêu cầu Coolify rebuild và
     redeploy container mới nhất từ nhánh `main`.

## Chạy thử cục bộ

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="xxx"
export ANTIGRAVITY_API_BASE="https://antigravity.example.com/v1"
export ANTIGRAVITY_API_KEY="xxx"
export AI_MODEL_NAME="gemini-2.0-flash"

python -u main.py
```

## Build Docker image thủ công

```bash
docker build -t telegram-antigravity-bot .
docker run --env-file .env telegram-antigravity-bot
```
