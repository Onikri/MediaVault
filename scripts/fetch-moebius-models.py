"""Optional real-inference weights; pinned downloads stay in the project cache."""
from pathlib import Path
import hashlib,urllib.request
root=Path(__file__).resolve().parents[1]/'.codex-local/cache/moebius'
root.mkdir(parents=True,exist_ok=True)
base='https://huggingface.co/simonw/Moebius-ONNX/resolve/5bf1ef5d2861ec01a727183a3f95dc64f352120e/'
for name,size,sha in [('vae_encoder.onnx',136757093,'b8b81d41e757222a0707665ba9d826703987855e5bed056036b90b988968042f'),('vae_decoder.onnx',198078671,'d90ef0b7f6c8c8b7234459c8b449d70be0033bf1576c842e8b9991baf3934280'),('unet.onnx',906698976,'e3f90f52f72378339b990459fadb29a68d3c7b5c6851545ba42774f489160b08')]:
    path=root/name
    if not path.is_file():
        temporary=root/(name+'.partial')
        with urllib.request.urlopen(base+name,timeout=120) as response,temporary.open('wb') as output:
            while chunk:=response.read(1024*1024):output.write(chunk)
        assert temporary.stat().st_size==size,name+' byte length'
        temporary.rename(path)
    with path.open('rb') as source:
        assert hashlib.file_digest(source,'sha256').hexdigest()==sha,name+' checksum'
    print(name,'verified',size,flush=True)
