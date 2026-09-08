import json
import re

from app.services.ai_service import chat_completion

SYSTEM_PROMPT = (
    "أنت مساعد يُنشئ أسئلة اختيار من متعدد (MCQ) من محتوى محاضرة دراسية. "
    "يجب أن يكون ردّك JSON صالحًا فقط، بدون أي نص أو شرح أو Markdown خارج "
    "الـ JSON، بالضبط بهذا الشكل:\n"
    '[{"question": "...", "options": ["...", "...", "...", "..."], '
    '"correct_index": 0}, ...]\n'
    "كل سؤال يجب أن يملك 4 خيارات بالضبط، وcorrect_index رقم من 0 إلى 3 "
    "يشير لموقع الإجابة الصحيحة داخل options. الأسئلة والخيارات باللغة العربية."
)

DIFFICULTY_HINT = {
    "سهل": "أسئلة مباشرة تختبر تعريفات ومفاهيم أساسية فقط.",
    "متوسط": "أسئلة تختبر الفهم والتطبيق البسيط للمفاهيم.",
    "صعب": "أسئلة تحليلية تربط بين عدة مفاهيم أو تختبر حالات دقيقة.",
}


class QuestionGenerationError(Exception):
    """يُرفع عندما يفشل تحليل استجابة النموذج كـ JSON صالح بالشكل المتوقَّع،
    حتى بعد محاولة تنظيفها — أفضل من إرجاع بيانات فاسدة للتطبيق."""


def _extract_json_array(raw: str) -> str:
    """النماذج أحيانًا تُحيط الـ JSON بحواجز Markdown (```json ... ```)
    رغم التعليمات الصريحة بعدم فعل ذلك؛ هذه دالة تنظيف دفاعية بسيطة."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    return match.group(0) if match else raw


def generate_questions(full_text: str, count: int, difficulty: str) -> list[dict]:
    hint = DIFFICULTY_HINT.get(difficulty, DIFFICULTY_HINT["متوسط"])
    user_prompt = (
        f"أنشئ {count} سؤال اختيار من متعدد من محتوى المحاضرة التالي. "
        f"مستوى الصعوبة: {difficulty} — {hint}\n\n"
        f"المحتوى:\n{full_text[:10000]}"
    )

    raw = chat_completion(SYSTEM_PROMPT, user_prompt)
    cleaned = _extract_json_array(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise QuestionGenerationError("تعذّر تحليل استجابة النموذج كأسئلة صالحة.") from e

    if not isinstance(data, list) or not data:
        raise QuestionGenerationError("النموذج لم يُعِد أي أسئلة.")

    validated = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        options = item.get("options")
        correct_index = item.get("correct_index")

        if (
            isinstance(question, str)
            and isinstance(options, list)
            and len(options) == 4
            and all(isinstance(o, str) for o in options)
            and isinstance(correct_index, int)
            and 0 <= correct_index < 4
        ):
            validated.append({
                "question": question,
                "options": options,
                "correct_index": correct_index,
            })

    if not validated:
        raise QuestionGenerationError("لم يُنتج النموذج أي سؤال بالشكل الصحيح المتوقَّع.")

    return validated
