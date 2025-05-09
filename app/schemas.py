# app/schemas.py
from pydantic import BaseModel, Field

# Если вы используете валидаторы полей из Pydantic V2, импорт может быть таким:
# from pydantic import BaseModel, Field, field_validator


class DocumentCreate(BaseModel):
    """Схема для валидации данных при создании (загрузке) документа."""

    name: str
    content: str = Field(..., min_length=11)  # Используем Field для валидации длины

    # Пример валидатора для Pydantic V2, если бы Field не использовался:
    # @field_validator("content")
    # def validate_content_length(cls, value: str) -> str:
    #     if len(value) <= 10:
    #         raise ValueError("Content length must be greater than 10 characters.")
    #     return value


class SearchResult(BaseModel):
    """Схема для представления одного результата поиска."""

    name: str  # Имя найденного документа
    score: float  # TF-IDF релевантность документа запросу


class DocumentResponse(BaseModel):
    """Схема для возврата информации о созданном или существующем документе."""

    id: int  # ID документа в базе данных
    name: str  # Имя документа
    word_count: int  # Общее количество слов в документе

    class Config:
        """
        Конфигурация Pydantic для модели.
        `from_attributes = True` позволяет Pydantic создавать
        экземпляры модели из ORM-объектов (например, объектов SQLAlchemy),
        автоматически считывая данные из их атрибутов.
        Это замена `orm_mode = True` из Pydantic V1.
        """

        # orm_mode = True  # Старый способ для Pydantic V1
        from_attributes = True  # Новый способ для Pydantic V2+
