# alembic/env.py
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- Настройка пути для импорта ---
# Добавляем корневую директорию проекта (/code в вашем Dockerfile) в sys.path
# __file__ здесь будет /code/alembic/env.py
# os.path.dirname(__file__) -> /code/alembic
# os.path.join(..., "..") -> /code
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# --- Импорты из вашего приложения ---
try:
    from app.database import (
        Base,  # Используем Base из вашего приложения /code/app/database.py
    )
    # from app import models       # Модели обычно подтягиваются через Base
except ImportError as e:
    print(f"Error importing application modules in env.py: {e}", file=sys.stderr)
    print(f"Current sys.path in env.py: {sys.path}", file=sys.stderr)
    raise

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
target_metadata = Base.metadata

# --- Настройка URL базы данных для Alembic ---
# Получаем URL из переменной окружения
DATABASE_URL_FROM_ENV = os.getenv("DATABASE_URL")
if not DATABASE_URL_FROM_ENV:
    # В production или CI/CD лучше выбрасывать ошибку, если переменная не найдена
    print(
        "CRITICAL: DATABASE_URL environment variable is not set for Alembic.",
        file=sys.stderr,
    )
    raise ValueError(
        "DATABASE_URL environment variable is not set for Alembic migrations."
    )

# Alembic требует синхронный URL
if DATABASE_URL_FROM_ENV.startswith("postgresql+asyncpg://"):
    SYNC_DATABASE_URL = DATABASE_URL_FROM_ENV.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
else:
    # Предполагаем, что URL уже синхронный или подходит для синхронного движка
    SYNC_DATABASE_URL = DATABASE_URL_FROM_ENV

# Устанавливаем этот URL в конфигурацию Alembic, чтобы engine_from_config его использовал
# Это изменит объект config 'на лету'
config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)
print(
    f"Alembic (env.py) is configured to use database URL: {SYNC_DATABASE_URL}"
)  # Для отладки


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # url теперь должен быть успешно получен из config, так как мы его установили
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # engine_from_config теперь должен найти 'sqlalchemy.url' в секции конфигурации,
    # которую мы модифицировали через config.set_main_option.
    # config.get_section(config.config_ini_section) вернет словарь опций из секции [alembic] (или другой указанной),
    # включая наш динамически добавленный 'sqlalchemy.url'.
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",  # Этот префикс означает, что ключ будет 'sqlalchemy.url'
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
