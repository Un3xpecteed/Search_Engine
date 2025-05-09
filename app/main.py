import asyncio
import os  # Для проверки RUNNING_IN_DOCKER
import sys
import time

from dotenv import load_dotenv  # Для локального запуска
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError

# Загружаем .env только если не в Docker, для локального запуска
# Это должно быть сделано до импорта других модулей, которые могут зависеть от env переменных
if not os.getenv("RUNNING_IN_DOCKER"):
    print("Loading .env file for local development (main.py)")
    load_dotenv()

# --- ИМПОРТЫ ЛОКАЛЬНЫХ МОДУЛЕЙ ---
# Помещаем их после load_dotenv, так как они могут использовать env переменные при инициализации
try:
    from .database import (  # SessionLocal для проверки соединения с БД
        SessionLocal,
        get_db,
    )
    from .schemas import DocumentCreate, DocumentResponse, SearchResult
    from .search_engine import SearchEngine
except ImportError as e:
    print(f"Error importing local modules in main.py: {e}", file=sys.stderr)
    print(f"Current sys.path: {sys.path}", file=sys.stderr)
    # Это критическая ошибка, приложение не сможет работать
    raise SystemExit(f"Failed to import local modules: {e}")

app = FastAPI(title="Document Search API", version="0.1.0")

search_engine_instance: SearchEngine | None = None


# --- ФУНКЦИЯ ЗАПУСКА МИГРАЦИЙ (С ЦИКЛОМ ПОВТОРА) ---
def run_migrations():
    """Запускает миграции Alembic с ожиданием БД."""
    alembic_ini_path = "alembic.ini"  # Путь относительно корня проекта
    # Если alembic.ini в /app, то /app/alembic.ini
    # Если в корне, то alembic.ini (Docker WORKDIR должен быть корень проекта)
    # В вашем примере был "/alembic.ini", что предполагает корень файловой системы контейнера.
    # Если alembic.ini лежит рядом с Dockerfile, то просто "alembic.ini" корректно,
    # если WORKDIR в Dockerfile установлен в корень проекта.

    print(f"Attempting to run Alembic migrations using config: {alembic_ini_path}")
    alembic_cfg = Config(alembic_ini_path)
    # Указываем путь к скриптам миграций относительно alembic.ini
    # Это обычно настраивается в самом alembic.ini (script_location)
    # alembic_cfg.set_main_option("script_location", "alembic")

    max_retries = 15
    retry_delay = 3  # секунды

    for attempt in range(max_retries):
        try:
            print(f"Migration attempt {attempt + 1}/{max_retries}...")
            # Проверка соединения с БД перед запуском миграций
            # Это необязательно, т.к. alembic сам попробует, но может дать более раннюю диагностику
            try:
                # Пытаемся создать сессию для проверки доступности БД
                # Это синхронная функция, поэтому не можем напрямую использовать async SessionLocal
                # Вместо этого, пусть Alembic сам обрабатывает ошибки соединения
                pass
            except OperationalError as db_err:
                print(
                    f"DB connection check failed (attempt {attempt + 1}): {db_err}. Retrying...",
                    file=sys.stderr,
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    raise RuntimeError(
                        "DB connection failed before migrations."
                    ) from db_err

            command.upgrade(alembic_cfg, "head")
            print("Alembic migrations finished successfully.")
            return  # Успех!
        except (OperationalError, CommandError) as e:
            error_str = str(e).lower()
            # Более общие проверки ошибок соединения
            if (
                isinstance(e, OperationalError)
                or "connection refused" in error_str
                or "could not connect" in error_str
                or "timeout" in error_str
                or "server" in error_str
                and "closed"
                in error_str  # e.g. "server closed the connection unexpectedly"
            ):
                print(
                    f"DB connection/command failed for migrations (attempt {attempt + 1}): {e}. Retrying in {retry_delay}s...",
                    file=sys.stderr,
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    print(
                        f"Max retries ({max_retries}) reached. Could not apply migrations.",
                        file=sys.stderr,
                    )
                    raise RuntimeError(
                        "Failed to apply migrations after multiple retries."
                    ) from e
            else:  # Другая ошибка Alembic, не связанная с соединением
                print(
                    f"!!! Alembic CommandError during migrations: {e}", file=sys.stderr
                )
                raise  # Перебрасываем, чтобы приложение не запустилось
        except Exception as e:
            print(
                f"!!! Unexpected error during Alembic migrations: {e}", file=sys.stderr
            )
            raise  # Перебрасываем, чтобы приложение не запустилось


@app.on_event("startup")
async def on_startup():
    global search_engine_instance
    try:
        print("Application startup sequence initiated...")

        # 1. Запуск миграций БД
        # Миграции - это блокирующая I/O операция, выполняем в экзекуторе
        print("Running database migrations...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, run_migrations
        )  # None использует ThreadPoolExecutor по умолчанию
        print("Database migrations task completed.")

        # 2. Инициализация поискового движка
        print("Initializing SearchEngine...")
        # SearchEngine теперь сам читает REDIS_URL из ENV при создании экземпляра
        search_engine_instance = SearchEngine()
        # Проверка соединения с Redis (опционально, SearchEngine может делать это внутри)
        try:
            await search_engine_instance.redis_client.ping()
            print("Successfully connected to Redis.")
        except Exception as redis_err:
            print(
                f"!!! Failed to connect to Redis during startup: {redis_err}",
                file=sys.stderr,
            )
            # Решите, является ли это критической ошибкой
            # raise RuntimeError(f"Startup failed: Could not connect to Redis: {redis_err}") from redis_err
            # Если Redis не критичен для _запуска_ (а только для работы), можно не падать
            print(
                "Warning: Search engine might not function correctly without Redis.",
                file=sys.stderr,
            )

        print("SearchEngine initialized.")
        print("Application startup successful.")

    except ValueError as e:  # Ловим ошибки конфигурации (напр., нет ENV VAR из SearchEngine или database)
        print(
            f"!!! Configuration error during startup (e.g., missing ENV VAR): {e}",
            file=sys.stderr,
        )
        # Это критическая ошибка, приложение не должно запускаться
        raise SystemExit(f"Startup configuration failed: {e}")
    except (
        RuntimeError
    ) as e:  # Ловим ошибки миграций или другие критические ошибки из startup
        print(f"!!! Critical error during application startup: {e}", file=sys.stderr)
        # Позволяем FastAPI обработать ошибку и не запуститься (или SystemExit)
        raise SystemExit(f"Application startup failed: {e}")
    except Exception as e:
        print(
            f"!!! Unexpected critical error during application startup: {e}",
            file=sys.stderr,
        )
        raise SystemExit(f"Unexpected application startup failure: {e}")


# --- ЭНДПОИНТЫ ---


@app.post("/upload/", response_model=DocumentResponse, status_code=201)
async def upload_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if search_engine_instance is None:
        raise HTTPException(
            status_code=503, detail="Search engine not initialized or not available."
        )

    file_content_bytes = await file.read()
    try:
        # Декодируем содержимое файла как UTF-8
        file_content_str = file_content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail=f"File '{file.filename}' is not valid UTF-8 encoded text.",
        )

    try:
        # Валидация через Pydantic (длина контента и т.д.)
        document_data = DocumentCreate(
            name=str(file.filename), content=file_content_str
        )
    except ValueError as e:  # Ошибка валидации Pydantic
        raise HTTPException(status_code=400, detail=f"Invalid file data: {e}")

    try:
        # search_engine.add_document теперь может сам обрабатывать IntegrityError
        # и возвращать созданный документ или рейзить ошибку
        created_doc = await search_engine_instance.add_document(
            db, document_data.name, document_data.content
        )
        if (
            created_doc is None
        ):  # Если add_document решил не добавлять (например, нет слов)
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' could not be processed (e.g., no content).",
            )
        # Возвращаем данные о созданном документе
        return DocumentResponse.from_orm(created_doc)  # Pydantic v1
        # return DocumentResponse.model_validate(created_doc) # Pydantic v2

    except IntegrityError:  # Если дубликат имени файла (unique constraint в БД)
        await db.rollback()  # Важно откатить, если add_document не сделал этого
        raise HTTPException(
            status_code=409,  # Conflict
            detail=f"Document with name '{file.filename}' already exists.",
        )
    except Exception as e:
        await db.rollback()  # Общий откат на всякий случай
        print(
            f"An unexpected error occurred during upload for '{file.filename}': {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        # Логирование полного стека ошибок здесь было бы полезно в продакшене
        # import traceback
        # traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the file.",
        )


@app.get("/search/", response_model=list[SearchResult])
async def search_documents(query: str, db: AsyncSession = Depends(get_db)):
    if search_engine_instance is None:
        raise HTTPException(
            status_code=503, detail="Search engine not initialized or not available."
        )

    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query parameter cannot be empty.")

    try:
        results = await search_engine_instance.search(db, query)
        return results
    except Exception as e:
        # В search_engine.search уже есть логирование, но здесь можно добавить контекст HTTP
        print(
            f"An unexpected error occurred during search for query '{query}': {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        raise HTTPException(
            status_code=500,
            detail="An error occurred during search. Please try again later.",
        )


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # Проверка доступности БД
    db_ok = False
    try:
        # Простой запрос к БД для проверки соединения
        result = await db.execute(select(1))
        if result.scalar_one() == 1:
            db_ok = True
    except Exception as e:
        print(f"Health check DB connection error: {e}", file=sys.stderr)
        db_ok = False

    # Проверка доступности Redis
    redis_ok = False
    if search_engine_instance and search_engine_instance.redis_client:
        try:
            await search_engine_instance.redis_client.ping()
            redis_ok = True
        except Exception as e:
            print(f"Health check Redis connection error: {e}", file=sys.stderr)
            redis_ok = False

    status_code = 200
    content = {"status": "ok", "database_status": "ok", "redis_status": "ok"}

    if not db_ok:
        content["database_status"] = "error"
        status_code = 503  # Service Unavailable
    if not redis_ok:
        content["redis_status"] = "error"
        status_code = 503  # Service Unavailable

    if status_code != 200:
        content["status"] = "degraded"  # или "error"

    return JSONResponse(status_code=status_code, content=content)


if __name__ == "__main__":
    # Это для локального запуска без Uvicorn CLI, например, для отладки
    # В продакшене используется `uvicorn app.main:app --host 0.0.0.0 --port 8000`
    import uvicorn

    print("Starting Uvicorn server for local development...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
