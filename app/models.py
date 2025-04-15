from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    content = Column(String, nullable=False)
    inverted_index = relationship("InvertedIndex", back_populates="document")


class InvertedIndex(Base):
    __tablename__ = "inverted_index"
    word = Column(String, primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id"), primary_key=True)
    count = Column(Integer, nullable=False)
    document = relationship("Document", back_populates="inverted_index")
