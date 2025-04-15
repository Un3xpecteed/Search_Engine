from pydantic import BaseModel, field_validator


class DocumentCreate(BaseModel):
    name: str
    content: str

    @field_validator("content")
    def validate_content_length(cls, value):
        if len(value) <= 10:
            raise ValueError("Content length must be greater than 10 characters.")
        return value


class SearchResult(BaseModel):
    name: str
    score: float
