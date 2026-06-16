import os

# این ماژول کلید OpenAI را از محیط می‌خواند و یک wrapper ساده برای ایجاد client فراهم می‌کند.
# توجه: هرگز کلید حقیقی را در مخزن ذخیره نکنید.

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')


def require_api_key():
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY تنظیم نشده است. مقدار آن را در فایل .env قرار دهید یا متغیر محیطی را تنظیم کنید."
        )


def create_openai_client():
    """بازگرداندن ماژول openai با api_key تنظیم‌شده. بسته openai را نصب کنید (pip install openai)."""
    require_api_key()
    try:
        import openai
    except Exception as exc:
        raise RuntimeError("برای استفاده از OpenAI لطفاً بسته `openai` را نصب کنید: pip install openai") from exc

    openai.api_key = OPENAI_API_KEY
    return openai


def get_api_key():
    """برای تست/لاگینگ امن، مقدار کلید را مستقیماً چاپ نکنید؛ این تابع فقط برای تست داخل سرور استفاده شود."""
    return OPENAI_API_KEY
