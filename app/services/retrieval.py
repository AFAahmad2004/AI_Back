import json
import math

from app.models.document_chunk import DocumentChunk
from app.services.ai_service import AIServiceUnavailable, AIServiceError, embed_text


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keyword_overlap_score(question: str, content: str) -> int:
    q_words = set(question.lower().split())
    c_words = set(content.lower().split())
    return len(q_words & c_words)


def retrieve_relevant_chunks(
    question: str,
    chunks: list[DocumentChunk],
    top_k: int = 4,
) -> tuple[list[DocumentChunk], str]:
    """
    يطبّق خط RAG الموضّح في §25: السؤال → بحث تشابه → أهم القطع.

    - إذا كانت المقاطع تملك Embeddings محفوظة (أُنشئت وقت الرفع لأن مفتاح
      Gemini كان مفعّلًا)، يُستخدم Embedding للسؤال نفسه + تشابه جيب
      التمام (Cosine Similarity) — بحث دلالي فعلي.
    - إن لم تتوفر Embeddings (مفتاح غير مُعرَّف، أو فشل الاتصال لحظيًا)،
      يتم التراجع تلقائيًا لبحث بسيط بتقاطع الكلمات المفتاحية، بحيث تبقى
      ميزة "اسأل AI" قابلة للاستخدام (بجودة أقل) بدل التعطّل الكامل.

    يُعيد (أفضل المقاطع، اسم الطريقة المستخدمة) للشفافية في الاستجابة.
    """
    chunks_with_embeddings = [c for c in chunks if c.embedding]

    if chunks_with_embeddings:
        try:
            question_embedding = embed_text(question)
            scored = sorted(
                chunks_with_embeddings,
                key=lambda c: -_cosine_similarity(question_embedding, json.loads(c.embedding)),
            )
            return scored[:top_k], "semantic"
        except (AIServiceUnavailable, AIServiceError):
            pass  # نتابع بالتراجع لبحث الكلمات المفتاحية أدناه

    scored = sorted(chunks, key=lambda c: -_keyword_overlap_score(question, c.content))
    return scored[:top_k], "keyword"
