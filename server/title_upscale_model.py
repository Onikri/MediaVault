"""Serve only the verified, attributed CPU neural models from the project cache."""
import hashlib,os
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
FILE='illustration-span-3f5245ed1abe.onnx'
SHA='3f5245ed1abe8ba2b5249b70989757a086874ee6346bdf33a71c21701a4b663d'
MODELS={FILE:(SHA,1673274),'illustration-denoise-9d2c5ff9ea79.onnx':('9d2c5ff9ea794d77976e69d41d9b84ffc99d4a2f0c7c11ba2eb05e040a2b69b6',1673274),'fsrcnn-313fe4371950.onnx':('313fe4371950fd90216db4d1ce6a8c9b513128c4e715b2363a11d6a52ccb0e36',35054)}
def install(app):
    def serve(name):
        sha,size=MODELS[name]
        root=Path(os.getenv('TITLE_MODEL_DIR',str(Path(__file__).resolve().parent/'.codex-local'/'models')))
        path=root/name
        if not path.is_file() or path.stat().st_size!=size:raise HTTPException(503,'Выбранная модель ещё не установлена.')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise HTTPException(503,'Не прошла проверка модели.')
        return FileResponse(path,media_type='application/octet-stream',headers={'Cache-Control':'public,max-age=31536000,immutable','X-Content-Type-Options':'nosniff'})
    for name in MODELS:
        # Explicit routes only: arbitrary filenames/paths are never accepted.
        def create_endpoint(filename):
            def endpoint():return serve(filename)
            return endpoint
        app.add_api_route('/models/'+name,create_endpoint(name),methods=['GET'])
