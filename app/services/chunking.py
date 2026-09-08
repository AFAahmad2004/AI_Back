def chunk_pages(pages: list[dict], chunk_size: int = 800, overlap: int = 100) -> list[dict]:
    """
    يقسّم نص كل صفحة إلى مقاطع (Chunks) بحجم ~chunk_size حرفًا مع تداخل
    overlap حرفًا بين كل مقطع والذي يليه (يمنع فقدان السياق عند حدود
    المقطع). التقسيم على حدود الكلمات وليس منتصف كلمة.

    يُعيد قائمة [{"chunk_index": 0, "page_number": 1, "content": "..."}, ...]
    جاهزة للحفظ في جدول DocumentChunks ثم توليد Embeddings لها (§25).
    """
    chunks = []
    index = 0

    for page in pages:
        text = page["text"]
        if not text:
            continue

        words = text.split()
        current: list[str] = []
        current_len = 0

        for word in words:
            current.append(word)
            current_len += len(word) + 1
            if current_len >= chunk_size:
                chunks.append({
                    "chunk_index": index,
                    "page_number": page["page_number"],
                    "content": " ".join(current),
                })
                index += 1
                # نُبقي آخر بضع كلمات (بما يقارب `overlap` حرفًا) كبداية للمقطع التالي.
                overlap_words: list[str] = []
                overlap_len = 0
                for w in reversed(current):
                    overlap_len += len(w) + 1
                    overlap_words.insert(0, w)
                    if overlap_len >= overlap:
                        break
                current = overlap_words
                current_len = overlap_len

        if current:
            chunks.append({
                "chunk_index": index,
                "page_number": page["page_number"],
                "content": " ".join(current),
            })
            index += 1

    return chunks
