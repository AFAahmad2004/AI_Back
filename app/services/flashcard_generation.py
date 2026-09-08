import json
import re

from app.services.ai_service import chat_completion

SYSTEM_PROMPT = (
    "أنت مساعد يُنشئ بطاقات تعليمية (Flashcards) من محتوى محاضرة دراسية. "
    "كل بطاقة يجب أن تحتوي على مصطلح أو سؤال قصير في 'front'، وشرح واضح "
    "ومختصر في 'back'. يجب أن يكون ردّك JSON صالحًا فقط، بدون أي نص أو "
    "شرح أو Markdown خارج الـ JSON، بالضبط بهذا الشكل:\n"
    '[{"front": "...", "back": "..."}, ...]\n'
    "باللغة العربية، إلا إذا كان المصطلح تقنيًا يُفضَّل بقاؤه بالإنجليزية "
    "(مثل TCP, OOP) مع شرح عربي في الجهة الخلفية."
)


class FlashcardGenerationError(Exception):
    """يُرفع عند فشل تحليل استجابة النموذج كـ JSON صالح بالشكل المتوقَّع."""


def _extract_json_array(raw: str) -> str:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    return match.group(0) if match else raw


def generate_flashcards(full_text: str, count: int) -> list[dict]:
    user_prompt = (
        f"أنشئ {count} بطاقة تعليمية (Flashcard) من أهم المصطلحات والمفاهيم "
        f"في محتوى المحاضرة التالي:\n\n{full_text[:10000]}"
    )

    raw = chat_completion(SYSTEM_PROMPT, user_prompt)
    cleaned = _extract_json_array(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise FlashcardGenerationError("تعذّر تحليل استجابة النموذج كبطاقات صالحة.") from e

    if not isinstance(data, list) or not data:
        raise FlashcardGenerationError("النموذج لم يُعِد أي بطاقات.")

    validated = []
    for item in data:
        if not isinstance(item, dict):
            continue
        front = item.get("front")
        back = item.get("back")
        if isinstance(front, str) and isinstance(back, str) and front.strip() and back.strip():
            validated.append({"front": front.strip(), "back": back.strip()})

    if not validated:
        raise FlashcardGenerationError("لم يُنتج النموذج أي بطاقة بالشكل الصحيح المتوقَّع.")

    return validated
