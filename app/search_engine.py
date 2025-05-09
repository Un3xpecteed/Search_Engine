# app/search_engine.py

import os
import pickle
import re
import sys
from asyncio import TimeoutError
from collections import Counter

import redis.asyncio as redis
from dotenv import load_dotenv
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем из локальных модулей (предполагается, что search_engine.py находится в пакете app)
from .models import Document, InvertedIndex
from .schemas import SearchResult

# Загружаем .env только если не в Docker, для локального запуска
if not os.getenv("RUNNING_IN_DOCKER"):
    print("Loading .env file for local development (search_engine.py)")
    load_dotenv()


def split_to_words(text: str) -> list[str]:
    """Разбивает текст на слова (токены)."""
    if not text:
        return []
    return re.findall(r"\b\w+\b", text.lower())


class SearchEngine:
    def __init__(self):
        """Инициализирует SearchEngine, настраивая подключение к Redis."""
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            print(
                "REDIS_URL environment variable is not set. Exiting.", file=sys.stderr
            )
            raise ValueError("REDIS_URL environment variable is not set.")

        print(f"SearchEngine connecting to Redis at: {redis_url}")
        try:
            self.redis_client = redis.Redis.from_url(redis_url, decode_responses=False)
        except Exception as e:
            print(f"Failed to connect to Redis: {e}", file=sys.stderr)
            raise RuntimeError(f"Failed to initialize Redis client: {e}") from e
        self.cache_ttl_seconds = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "3600"))

    async def add_document(self, db: AsyncSession, name: str, content: str):
        """
        Добавляет документ в базу данных и обновляет инвертированный индекс.
        Очищает кэш Redis, так как добавление нового документа может повлиять на результаты поиска.
        """
        words = split_to_words(content)
        if not words:
            print(
                f"Document '{name}' contains no processable words. Skipping.",
                file=sys.stderr,
            )
            return None  # Возвращаем None, чтобы вызывающий код мог это обработать

        word_counts = Counter(words)
        total_words_in_doc = len(words)

        new_doc = Document(name=name, content=content, word_count=total_words_in_doc)
        db.add(new_doc)

        try:
            await db.commit()
            await db.refresh(new_doc)

            index_entries = [
                InvertedIndex(word=word, doc_id=new_doc.id, count=count)
                for word, count in word_counts.items()
            ]
            if index_entries:
                db.add_all(index_entries)
                await db.commit()

            try:
                await self.redis_client.flushdb()
                print(f"Redis cache flushed due to document addition: {name}")
            except (RedisConnectionError, TimeoutError, Exception) as e:
                print(
                    f"Warning: Failed to flush Redis cache during add_document: {e}",
                    file=sys.stderr,
                )

            print(
                f"Added document '{name}' (ID: {new_doc.id}) with {total_words_in_doc} words."
            )
            return new_doc

        except Exception as e:
            await db.rollback()
            print(f"Error adding document '{name}': {e}", file=sys.stderr)
            raise  # Перебрасываем, чтобы FastAPI обработал (например, IntegrityError)

    async def search(self, db: AsyncSession, query: str) -> list[SearchResult]:
        """
        Ищет документы, релевантные запросу, используя TF-IDF.
        Сначала проверяет кэш Redis, затем обращается к базе данных.
        """
        query_lower = query.lower().strip()
        if not query_lower:
            print("Search query is empty. Returning empty list.")
            return []

        cache_key = f"search:{query_lower}"
        try:
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                print(f"Cache hit for query: '{query}'")
                results = pickle.loads(cached_data)
                return results
        except (
            pickle.UnpicklingError,
            RedisConnectionError,
            TimeoutError,
            Exception,
        ) as e:
            print(
                f"Cache read failed for query '{query}': {e}. Recalculating.",
                file=sys.stderr,
            )

        print(f"Cache miss or error for query: '{query}'. Searching in DB.")
        query_words = split_to_words(query_lower)
        print(f"Search query processed into words: {query_words}")
        if not query_words:
            print("No processable words in query. Returning empty list.")
            return []

        try:
            # 1. Получение общего количества документов (N)
            total_documents_stmt = select(func.count(Document.id))
            total_documents_res = await db.execute(total_documents_stmt)
            total_documents = total_documents_res.scalar_one_or_none() or 0
            print(f"Total documents in DB (N): {total_documents}")

            if total_documents == 0:
                print("No documents in DB. Returning empty list.")
                return []

            # 2. df_subq: подзапрос для document frequency (df)
            df_subq = (
                select(InvertedIndex.word, func.count(InvertedIndex.doc_id).label("df"))
                .where(InvertedIndex.word.in_(query_words))
                .group_by(InvertedIndex.word)
                .subquery("df_subq")
            )

            # 3. IDF = log((N + 1) / (df + 1))
            log_idf_expr = func.log(
                (cast(total_documents, Float) + 1.0)
                / (
                    func.greatest(df_subq.c.df, 0) + 1.0
                )  # greatest(df, 0) если df может быть None/отсутствовать
            )

            # 4. TF = count(word, doc) / total_words_in_doc
            tf_expr = cast(InvertedIndex.count, Float) / cast(
                func.greatest(Document.word_count, 1),
                Float,  # greatest(wc, 1) для избежания деления на ноль
            )

            # 5. Score = sum(TF * IDF)
            score_expr = func.sum(tf_expr * log_idf_expr)

            stmt = (
                select(
                    Document.id.label("doc_id"),
                    Document.name.label("doc_name"),
                    score_expr.label("total_score"),
                )
                .select_from(InvertedIndex)
                .join(Document, InvertedIndex.doc_id == Document.id)
                .join(df_subq, InvertedIndex.word == df_subq.c.word)
                .where(InvertedIndex.word.in_(query_words))
                .group_by(Document.id, Document.name)
                .order_by(score_expr.desc())
                .limit(10)
            )

            print("Executing search SQL query...")
            db_results = await db.execute(stmt)
            rows = db_results.all()
            print(f"Raw DB results (rows) for query '{query}': {rows}")

            results = []
            for row in rows:
                print(
                    f"  Processing row: doc_name='{row.doc_name}', total_score={row.total_score}"
                )
                # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
                # Позволяем документам с нулевым скором быть в результатах
                if row.total_score is not None and row.total_score >= 0:
                    results.append(
                        SearchResult(name=row.doc_name, score=float(row.total_score))
                    )
                else:
                    print(
                        f"  Skipping row for doc_name='{row.doc_name}' due to score: {row.total_score}"
                    )

            print(f"Final processed results for query '{query}': {results}")

            # 6. Кэширование результатов
            if results:  # Кэшируем, только если есть результаты
                try:
                    pickled_results = pickle.dumps(results)
                    await self.redis_client.set(
                        cache_key, pickled_results, ex=self.cache_ttl_seconds
                    )
                    print(
                        f"Cached results for query: '{query}' (TTL: {self.cache_ttl_seconds}s)"
                    )
                except (RedisConnectionError, TimeoutError, Exception) as e:
                    print(
                        f"Cache write failed for query '{query}': {e}", file=sys.stderr
                    )
            elif rows:  # Если были строки из БД, но они отфильтровались
                print(
                    f"No qualifying results for query '{query}' after filtering, nothing to cache."
                )
            else:  # Если БД ничего не вернула
                print(f"No results found in DB for query '{query}', nothing to cache.")

            return results

        except Exception as e:
            print(
                f"Database search error for query '{query}': {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            # В случае ошибки возвращаем пустой список, чтобы не сломать клиент
            # Можно также перевыбросить ошибку, если это предпочтительнее для глобальной обработки
            # import traceback
            # traceback.print_exc() # Для более детальной информации об ошибке
            return []
