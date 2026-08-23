# main.py
from fastapi import FastAPI
from config import settings
from jobs import DB_PATH

app = FastAPI(title="Revercion2")

@app.get("/")
async def root():
    return {"status": "ok", "db_path": str(DB_PATH)}