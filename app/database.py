import os
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Загружаем переменные из .env файла (полезно для локального запуска без Docker)
# Обычно это делается один раз при старте приложения, но для модульности можно здесь
# Однако, если main.py тоже делает load_dotenv(), убедитесь, что это не вызывает конфликтов
# или что load_dotenv() вызывается только один раз (например, в main.py перед импортами).
# Для простоты оставим здесь, предполагая, что это основной источник конфигурации БД.
if not os.getenv("RUNNING_IN_DOCKER"):  # Условная загрузка для локальной разработки
    print("Loading .env file for local development (database.py)")
    load_dotenv()

# Читаем URL из переменной окружения DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL environment variable is not set. Exiting.", file=sys.stderr)
    # В реальном приложении лучше выбросить ошибку или завершить работу
    raise ValueError("DATABASE_URL environment variable is not set.")

print(f"Database URL used by SQLAlchemy: {DATABASE_URL}")  # Для отладки

# Создаем движок с URL из окружения
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # echo=True для детальных логов SQL, False для продакшена
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,  # Рекомендуется для async
    autocommit=False,  # Рекомендуется для async
)

Base = declarative_base()


async def get_db():
    """
    Dependency to get an async database session.
    Ensures the session is closed after the request.
    """
    async with SessionLocal() as session:
        try:
            yield session
            # Не вызываем commit здесь, пусть роуты сами решают когда коммитить
        except Exception:
            await session.rollback()  # Откатываем транзакцию в случае ошибки в роуте
            raise
        finally:
            await session.close()  # Закрываем сессию
