"""Serve only the verified, attributed CPU SPAN model from the project cache."""
import hashlib,os
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
FILE='illustration-span-3f5245ed1abe.onnx'
SHA='3f5245ed1abe8ba2b5249b70989757a086874ee6346bdf33a71c21701a4b663d'
def install(app):
    @app.get('/models/'+FILE)
    def weights():
        root=Path(os.getenv('TITLE_MODEL_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'models')))
        path=root/FILE
        if not path.is_file() or path.stat().st_size!=1673274:raise HTTPException(503,'Модель фона ещё не установлена.')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise HTTPException(503,'Не прошла проверка модели фона.')
        return FileResponse(path,media_type='application/octet-stream',headers={'Cache-Control':'public,max-age=31536000,immutable','X-Content-Type-Options':'nosniff'})
