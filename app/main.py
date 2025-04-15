from fastapi import Depends, FastAPI, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .schemas import DocumentCreate, SearchResult
from .search_engine import SearchEngine

app = FastAPI()
search_engine = SearchEngine()


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    file_content = await file.read()
    document = DocumentCreate(name=file.filename, content=file_content.decode("utf-8"))
    await search_engine.add_document(db, document.name, document.content)
    return {"message": f"File '{file.filename}' uploaded successfully."}


@app.get("/search/")
async def search(query: str, db: AsyncSession = Depends(get_db)) -> list[SearchResult]:
    return await search_engine.search(db, query)


