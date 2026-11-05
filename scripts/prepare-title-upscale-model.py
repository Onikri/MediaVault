"""Reproduce the separately cached, CPU-compatible IllustrationJaNai weights.

Run from the checkout with project-local requests/numpy/onnx dependencies. Only
one ZIP member is downloaded using HTTP Range. Weights are never committed.
"""
import argparse,hashlib,io,json,zipfile
from pathlib import Path
import requests,numpy as np,onnx

ARCHIVE='https://github.com/the-database/MangaJaNai/releases/download/3.0.0/IllustrationJaNai_V3detail_onnx.zip'
MEMBER='2x_IllustrationJaNai_V3detail_SPAN_S_40k_fp16_1x3xHxW_dyn-HW_strong_fp16_op23.onnx'
ORIGINAL='00b6a70642914371453bec96fbb7087697651c12ae8b0a3dbde5b9b4d82435b1'
EXPECTED='3f5245ed1abe8ba2b5249b70989757a086874ee6346bdf33a71c21701a4b663d'

def convert(graph):
    for value in [*graph.input,*graph.output,*graph.value_info]:
        if value.type.HasField('tensor_type') and value.type.tensor_type.elem_type==onnx.TensorProto.FLOAT16:value.type.tensor_type.elem_type=onnx.TensorProto.FLOAT
    for i,tensor in enumerate(graph.initializer):
        if tensor.data_type==onnx.TensorProto.FLOAT16:graph.initializer[i].CopyFrom(onnx.numpy_helper.from_array(onnx.numpy_helper.to_array(tensor).astype(np.float32),tensor.name))
    for node in graph.node:
        for attr in node.attribute:
            if attr.type==onnx.AttributeProto.TENSOR and attr.t.data_type==onnx.TensorProto.FLOAT16:attr.t.CopyFrom(onnx.numpy_helper.from_array(onnx.numpy_helper.to_array(attr.t).astype(np.float32),attr.t.name))
            elif attr.type==onnx.AttributeProto.GRAPH:convert(attr.g)
            elif attr.name=='to' and attr.i==onnx.TensorProto.FLOAT16:attr.i=onnx.TensorProto.FLOAT

def main():
    global ARCHIVE,MEMBER,ORIGINAL,EXPECTED
    parser=argparse.ArgumentParser();parser.add_argument('--profile',choices=['detail','denoise','fast'],default='detail');args=parser.parse_args()
    root=Path('.codex-local/models');root.mkdir(parents=True,exist_ok=True)
    if args.profile=='fast':
        manifest=json.loads(Path('reader-models/title-fsrcnn.json').read_text());url=manifest['source'].replace('github.com/','raw.githubusercontent.com/').replace('/blob/','/');response=requests.get(url,timeout=30);response.raise_for_status();raw=response.content
        if len(raw)!=manifest['bytes'] or hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise RuntimeError('FSRCNN checksum mismatch')
        output=root/'fsrcnn-313fe4371950.onnx';output.write_bytes(raw);print(output);return
    if args.profile=='denoise':
        manifest=json.loads(Path('reader-models/title-denoise.json').read_text());ARCHIVE=manifest['archive'];MEMBER=manifest['member'];ORIGINAL=manifest['sha256'];EXPECTED=manifest['convertedSha256']
    with requests.get(ARCHIVE,stream=True,timeout=30) as response:
        response.raise_for_status();size=int(response.headers['Content-Length']);url=response.url
    class Remote(io.RawIOBase):
        pos=0
        def seekable(self):return True
        def tell(self):return self.pos
        def seek(self,offset,whence=0):
            self.pos=offset if whence==0 else self.pos+offset if whence==1 else size+offset
            return self.pos
        def read(self,count=-1):
            if count<0:count=size-self.pos
            if not count:return b''
            with requests.get(url,headers={'Range':f'bytes={self.pos}-{min(size-1,self.pos+count-1)}'},timeout=30) as response:
                if response.status_code!=206:raise RuntimeError('Archive server does not support partial reads')
                data=response.content
            self.pos+=len(data);return data
    with zipfile.ZipFile(Remote()) as archive:raw=archive.read(MEMBER)
    if hashlib.sha256(raw).hexdigest()!=ORIGINAL:raise RuntimeError('Upstream model checksum mismatch')
    model=onnx.load_model_from_string(raw);convert(model.graph)
    # This graph uses no IR12-only types/features. Checker and real CPU/WASM
    # inference validate the compatible IR11 declaration (network unchanged).
    model.ir_version=11;onnx.checker.check_model(model)
    output=root/('illustration-denoise-9d2c5ff9ea79.onnx' if args.profile=='denoise' else 'illustration-span-3f5245ed1abe.onnx');onnx.save(model,output)
    if hashlib.sha256(output.read_bytes()).hexdigest()!=EXPECTED:output.unlink();raise RuntimeError('Converted model checksum mismatch')
    print(output)

if __name__=='__main__':main()
