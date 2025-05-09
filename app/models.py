from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base  # Импортируем Base из нашего модуля database


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False, index=True)
    content = Column(String, nullable=False)
    word_count = Column(Integer, nullable=False, default=0)

    # Связь с InvertedIndex: один документ может иметь много записей в инвертированном индексе
    inverted_index_entries = relationship(
        "InvertedIndex", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Document(id={self.id}, name='{self.name}')>"


class InvertedIndex(Base):
    __tablename__ = "inverted_index"

    # Составной первичный ключ
    word = Column(String, primary_key=True, index=True)
    doc_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    count = Column(Integer, nullable=False)  # Количество вхождений слова в документе

    # Связь с Document: каждая запись индекса принадлежит одному документу
    document = relationship("Document", back_populates="inverted_index_entries")

    def __repr__(self):
        return f"<InvertedIndex(word='{self.word}', doc_id={self.doc_id}, count={self.count})>"
