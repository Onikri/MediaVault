"""Bounded Alloha -> fragmented MP4 pipe -> encrypted Drive chunks.

Only loopback manifests reach ffmpeg. NativeSession owns all upstream I/O.
No film, HLS media cache or unencrypted chunk is retained on disk.
"""
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import secrets
import subprocess
import threading

from source_parser import MAX_VIDEO, SourceError
from vault_drive import CHUNK_SIZE
from alloha_import import PREFIX


logger = logging.getLogger(__name__)


class StreamingVideo:
    def __init__(self, http, directory, *, checkpoint=None):
        self.http, self.directory = http, Path(directory)
        self.http.cache_media = False
        self.checkpoint = Path(checkpoint)/'stream.enc.json' if checkpoint else None
        self.process = self.server = None
        self.loaded = 0
        self.first = b''
        self.tail = b''
        self.last_time = 0
        self.completed = False
        self.failure = None
        self.diagnostics = []
        self.lock = threading.Lock()

    @contextmanager
    def opened(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.http.call(self.http.open())
            if self.http.quality != 'best' and self.http.selected != str(self.http.quality):
                raise SourceError('Alloha сейчас не отдаёт выбранное качество. Другое качество не сохранено.')
            # The playlist layout is checked again on every session renewal.
            import m3u8
            media = [m3u8.loads(text) for text in self.http.documents.values()]
            self.duration = max(sum(float(s.duration) for s in p.segments) for p in media)
            if self.duration <= 0:
                raise SourceError('В источнике нет законченного фильма.')
            secret = '/' + secrets.token_urlsafe(24) + '/'
            video = self
            mapped_tracks = {name.rsplit('-map-', 1)[0]
                             for name, resource in self.http.resources.items() if resource[2] == 'map'}

            def resource_name(name):
                if PREFIX + name in self.http.documents:
                    return name + '.m3u8'
                kind = self.http.resources[name][2]
                if kind == 'key':
                    return name + '.key'
                if kind == 'map':
                    return name + '.mp4'
                track = name.rsplit('-segment-', 1)[0]
                return name + ('.m4s' if track in mapped_tracks else '.ts')
            self.routes = {resource_name(name): name for name in self.http.resources}
            self.routes.update({resource_name(url.removeprefix(PREFIX)): url.removeprefix(PREFIX) for url in self.http.documents})

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    if not self.path.startswith(secret):
                        self.send_error(404)
                        return
                    name = video.routes.get(self.path[len(secret):])
                    if name is None:
                        self.send_error(404)
                        return
                    try:
                        with video.lock:
                            if video.http.cancelled():
                                raise SourceError('Импорт отменён владельцем.')
                            if PREFIX + name in video.http.documents:
                                body = re.sub(re.escape(PREFIX) + r'[\w-]+',
                                    lambda m: video.local + resource_name(m[0].removeprefix(PREFIX)),
                                    video.http.documents[PREFIX + name]).encode()
                                mime = 'application/vnd.apple.mpegurl'
                            elif name in video.http.resources:
                                body = video.http.call(video.http.fetch(name))
                                mime = 'application/octet-stream'
                                video.http.saved_resources.add(name)
                                video.http.progress({'phase': 'downloading', 'operation':
                                    f'Alloha → шифрование → Drive · {len(video.http.saved_resources)} / {len(video.http.resources)} частей'})
                            else:
                                self.send_error(404)
                                return
                        self.send_response(200)
                        self.send_header('Content-Type', mime)
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    except Exception as error:
                        video.failure = error
                        with suppress(BrokenPipeError, ConnectionResetError):
                            self.send_error(502)

            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.local = 'http://127.0.0.1:' + str(self.server.server_port) + secret
            worker = threading.Thread(target=self.server.serve_forever, daemon=True)
            worker.start()
            self.process = subprocess.Popen([
                'ffmpeg', '-nostdin', '-v', 'error', '-progress', 'pipe:2',
                '-protocol_whitelist', 'http,tcp,crypto', '-allowed_extensions', 'ALL',
                '-i', self.local + 'root.m3u8', '-map', '0:v:0', '-map', '0:a:0?',
                '-c', 'copy', '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
                '-frag_duration', '4000000', '-f', 'mp4', 'pipe:1'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def progress():
                for raw in self.process.stderr:
                    line = raw.decode('utf-8', 'replace').strip()
                    if line.startswith('out_time_us='):
                        try:
                            self.last_time = int(line.split('=', 1)[1]) / 1000000
                        except ValueError:
                            pass
                    elif line == 'progress=end':
                        self.completed = True
                    elif line and '=' not in line:
                        self.diagnostics = (self.diagnostics + [line[:500]])[-12:]
            reporter = threading.Thread(target=progress, daemon=True)
            self.reporter = reporter
            reporter.start()
            # Keep only a header sample to check real codecs, dimensions/audio.
            self.first = self.process.stdout.read(CHUNK_SIZE)
            sample = self.directory / 'stream-header.mp4'
            try:
                sample.write_bytes(self.first)
                probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                    'stream=codec_type,width,height', '-of', 'json', str(sample)],
                    capture_output=True, timeout=20)
                info = json.loads(probe.stdout)
                streams = info.get('streams', [])
                picture = next(s for s in streams if s.get('codec_type') == 'video')
                self.width, self.height = picture['width'], picture['height']
                if not any(s.get('codec_type') == 'audio' for s in streams):
                    raise SourceError('В потоке отсутствует звук выбранной озвучки.')
            except (KeyError, StopIteration, ValueError):
                raise SourceError('Не удалось проверить начало видеопотока. ffmpeg: ' + ' '.join(self.diagnostics)[-1200:]) from None
            finally:
                sample.unlink(missing_ok=True)
            yield self
            reporter.join(timeout=10)
        finally:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
                if hasattr(self, 'reporter'):
                    self.reporter.join(timeout=2)
                self.process.stdout.close()
                self.process.stderr.close()
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            self.http.call(self.http.close(), cleanup=True)

    def read(self, size):
        if self.http.cancelled():
            raise SourceError('Импорт отменён владельцем.')
        if self.first:
            value, self.first = self.first, b''
        else:
            value = self.process.stdout.read(size)
        self.loaded += len(value)
        if value:
            self.tail = (self.tail + value[-16:])[-16:]
        if self.loaded > MAX_VIDEO:
            raise SourceError('Видео превышает лимит импорта.')
        return value

    def validate(self):
        status = self.process.wait(timeout=30)
        self.reporter.join(timeout=10)
        if self.failure:
            raise SourceError('Alloha прервал передачу. Незавершённый фильм не опубликован.') from self.failure
        missing = self.http.resources.keys() - self.http.saved_resources
        # FFmpeg finishes a fragmented MP4 with a random access index. A
        # partial pipe can carry valid frames and still lack this final box.
        index_size = int.from_bytes(self.tail[12:], 'big')
        indexed = (self.tail[:8] == b'\x00\x00\x00\x10mfro'
                   and 24 <= index_size <= self.loaded)
        # EXTINF is a sum of declared segment lengths, not the final packet
        # timestamp. Small per-segment differences accumulate in long films.
        duration_tolerance = max(3, self.duration * .005)
        if (status or not self.completed or not indexed or self.diagnostics or missing
                or abs(self.last_time - self.duration) > duration_tolerance):
            logger.warning(
                'Alloha MP4 validation failed: exit=%s ended=%s indexed=%s diagnostics=%d missing=%d duration=%.3f expected=%.3f',
                status, self.completed, indexed, len(self.diagnostics), len(missing), self.last_time, self.duration,
            )
            raise SourceError('Фильм получен не полностью. Незавершённый файл не опубликован.')
        return {'width': self.width, 'height': self.height, 'duration': self.last_time, 'audio': True}

    def upload(self, vault, **options):
        with self.opened():
            return vault.upload_stream(self, validate=self.validate, quality=int(self.http.selected),
                                       checkpoint=self.checkpoint, stream_identity=self.http.fingerprint, **options)
