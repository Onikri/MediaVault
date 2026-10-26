"""Reproducible real inference and host measurements. Never labels local runs as Oracle."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server' if (ROOT / 'server').is_dir() else ROOT))


def inventory():
    import psutil
    memory = psutil.virtual_memory()
    return {'hostname': platform.node(), 'system': platform.platform(), 'architecture': platform.machine(),
            'logicalCpus': os.cpu_count(), 'loadAverage': list(os.getloadavg()) if hasattr(os, 'getloadavg') else None,
            'ramBytes': memory.total, 'availableRamBytes': memory.available,
            'diskFreeBytes': shutil.disk_usage(ROOT).free, 'python': platform.python_version(),
            'cgroupMemoryLimit': read_text('/sys/fs/cgroup/memory.max'),
            'cgroupCpuLimit': read_text('/sys/fs/cgroup/cpu.max')}


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


class Measurement:
    def __init__(self, extra_pids=()):
        self.extra_pids = extra_pids

    def __enter__(self):
        import psutil
        self.process = psutil.Process()
        self.peak = 0
        self.stop = threading.Event()
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        def sample():
            while not self.stop.is_set():
                try:
                    rss = self.process.memory_info().rss
                    processes = {p.pid:p for p in self.process.children(recursive=True)}
                    for pid in self.extra_pids:
                        try:
                            extra=psutil.Process(pid);processes[pid]=extra
                            processes.update({p.pid:p for p in extra.children(recursive=True)})
                        except psutil.Error:
                            pass
                    for child in processes.values():
                        try:
                            rss += child.memory_info().rss
                        except psutil.Error:
                            pass
                    self.peak = max(self.peak, rss)
                except psutil.Error:
                    pass
                self.stop.wait(.05)
        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.values = {'wallSeconds': round(time.perf_counter()-self.started, 3),
                       'pythonCpuSeconds': round(time.process_time()-self.cpu_started, 3),
                       'peakProcessTreeRssBytes': self.peak,
                       'rssNote': 'sum of resident pages, including shared pages; sampled every 50 ms'}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['inventory','upscale','lmt','combined'], default='inventory')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--models', type=Path, default=ROOT/'.codex-local/models/mangajanai')
    parser.add_argument('--data', type=Path, default=ROOT/'.codex-local/benchmark')
    parser.add_argument('--model', default='auto')
    parser.add_argument('--scale', type=int, choices=[1,2,4], default=2)
    parser.add_argument('--tile', type=int, choices=[64,128,256,512], default=128)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--runs', type=int, choices=range(1,6), default=2)
    parser.add_argument('--language', default='English')
    parser.add_argument('--ocr', default='paddle')
    parser.add_argument('--detector', choices=['comic-bubble','comic-text-detector'], default='comic-bubble')
    parser.add_argument('--inpaint', choices=['fast','quality'], default='fast')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--save-result', type=Path, help='Optional private preview of the last result')
    parser.add_argument('--save-transcript', type=Path, help='Optional private OCR/translation transcript for quality review')
    parser.add_argument('--include-pid', type=int, action='append', default=[], help='Include a separate local LLM process in RSS sampling')
    args = parser.parse_args()
    report = {'host': inventory(), 'mode': args.mode, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'runs': []}
    def save_report():
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.mode != 'inventory':
        if not args.image:
            parser.error('--image is required for real inference')
        if args.threads < 1 or args.threads > (os.cpu_count() or 1):
            parser.error('Invalid CPU thread limit')
        if report['host']['availableRamBytes'] < 1_500_000_000:
            raise RuntimeError('Less than 1.5 GB available RAM; benchmark did not start')
        os.environ['OMP_NUM_THREADS'] = str(args.threads)
        os.environ['MKL_NUM_THREADS'] = str(args.threads)
        os.environ['MANGAJANAI_DEVICE'] = 'cpu'
        os.environ['MANGAJANAI_MODEL_DIR'] = str(args.models.resolve())
        from reader_processing import Processor, ProcessOptions
        processor = Processor(args.data)
        data = args.image.read_bytes()
        report['input'] = {'name': args.image.name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes':len(data)}
        options = ProcessOptions(translate=args.mode in {'lmt','combined'}, upscale=args.mode in {'upscale','combined'},
                                 language=args.language, ocr=args.ocr, detector=args.detector, inpaint=args.inpaint, allowDownloads=True,
                                 scale=args.scale, tile=args.tile, model=args.model).model_dump()
        report['options'] = options
        try:
            for run in range(args.runs):
                job = {'data':data, 'options':options, 'subject':'benchmark', 'cancel':False}
                measurement = Measurement(args.include_pid)
                try:
                    with measurement:
                        result = await asyncio.wait_for(processor._process(job), timeout=900)
                    if not result.get('renderedImage'):
                        raise RuntimeError('Pipeline returned no rendered page; this is not a completed inference measurement')
                except BaseException as error:
                    record = {'run':run+1, 'success':False, 'firstRunInProcess':run==0,
                              **measurement.values, 'errorType':type(error).__name__,
                              'lastStage':job.get('status','decode')}
                    report['runs'].append(record)
                    print(json.dumps(record,ensure_ascii=False),flush=True)
                    raise
                record = {'run':run+1, 'success':True, 'firstRunInProcess':run==0, **measurement.values,
                          'upscale':result.get('upscale'), 'regions':len(result.get('regions', [])),
                          'timings':result.get('timings'), 'inpaintRegions':result.get('inpaintRegions'),
                          'renderedImageBytes':len(base64.b64decode(result['renderedImage']))}
                report['runs'].append(record)
                if args.save_result and result.get('renderedImage'):
                    args.save_result.parent.mkdir(parents=True, exist_ok=True)
                    args.save_result.write_bytes(base64.b64decode(result['renderedImage']))
                if args.save_transcript:
                    args.save_transcript.parent.mkdir(parents=True, exist_ok=True)
                    args.save_transcript.write_text(json.dumps(result.get('regions',[]),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps(record), flush=True)
                save_report()
        finally:
            try:
                await processor.close()
            finally:
                save_report()
    save_report()
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
