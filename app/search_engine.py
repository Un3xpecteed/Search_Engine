import pickle
import re
from collections import Counter, defaultdict
from math import log

import redis.asyncio as redis
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .models import Document, InvertedIndex
from .schemas import SearchResult


async def split_to_words(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


class SearchEngine:
    def __init__(self, redis_url="redis://localhost:6379"):
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=False)

    async def add_document(self, db: AsyncSession, name: str, content: str):
        new_doc = Document(name=name, content=content)
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)

        words = await split_to_words(content)
        word_counts = Counter(words)

        for word, count in word_counts.items():
            db.add(InvertedIndex(word=word, doc_id=new_doc.id, count=count))
        await db.commit()

        await self.redis_client.flushdb()

    async def search(self, db: AsyncSession, query: str) -> list[SearchResult]:
        cached_results = await self.redis_client.get(query)
        if cached_results:
            return pickle.loads(cached_results)

        query_words = await split_to_words(query)
        scores = defaultdict(float)

        total_documents = await db.scalar(select(func.count()).select_from(Document))
        if total_documents == 0:
            return []

        for word in query_words:
            results = await db.execute(
                select(InvertedIndex).where(InvertedIndex.word == word)
            )
            inverted_index_results = results.scalars().all()

            if inverted_index_results:
                idf = (
                    log((total_documents + 1) / (len(inverted_index_results) + 1))
                    if total_documents > 1
                    else 1.0
                )
                for entry in inverted_index_results:
                    doc = await db.get(Document, entry.doc_id)
                    tf = entry.count / len(await split_to_words(doc.content))
                    scores[entry.doc_id] += tf * idf

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = [
            SearchResult(name=(await db.get(Document, doc_id)).name, score=score)
            for doc_id, score in sorted_scores
        ]

        await self.redis_client.set(query, pickle.dumps(results))
        return results
