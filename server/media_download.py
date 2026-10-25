"""Download one episode inside Colab, then remux local files with ffmpeg.

No media URL is sent to ffmpeg: nested HLS playlists, maps, keys and segments
are fetched by the source-only HTTP client and rewritten to local files.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

import m3u8

from source_parser import MAX_VIDEO, SourceError, playback_headers


def pick_stream(streams, quality="720"):
    candidates = [entry for entry in streams if entry.get("type") in {"hls", "mp4"}]
    cap = None if quality == "best" else int(quality)
    known = [entry for entry in candidates if entry.get("quality") and (cap is None or int(entry["quality"]) <= cap)]
    if known:
        return max(known, key=lambda entry: (int(entry["quality"]), entry["type"] == "mp4"))
    unknown = [entry for entry in candidates if not entry.get("quality")]
    if unknown:
        return next((entry for entry in unknown if entry["type"] == "hls"), unknown[0])
    raise SourceError("Нет потока в выбранном качестве. Выбери другое качество.")


def choose_variant(playlists, quality):
    cap = None if quality == "best" else int(quality)
    candidates = [entry for entry in playlists
                  if entry.stream_info.resolution and (cap is None or entry.stream_info.resolution[1] <= cap)]
    if not candidates:
        candidates = [entry for entry in playlists if not entry.stream_info.resolution]
    if not candidates:
        raise SourceError("В HLS нет качества в пределах выбранного ограничения.")
    return max(candidates, key=lambda entry: (entry.stream_info.resolution or (0, 0), entry.stream_info.bandwidth or 0))


def byte_range(value, url, offsets):
    if not value:
        return None
    try:
        parts = value.split("@")
        length = int(parts[0])
        start = int(parts[1]) if len(parts) == 2 else offsets[url]
        if length <= 0 or start < 0:
            raise ValueError
    except (ValueError, KeyError, IndexError):
        raise SourceError("Некорректный диапазон сегмента HLS.") from None
    offsets[url] = start + length
    return f"bytes={start}-{start + length - 1}"


class HlsDownload:
    def __init__(self, http, directory, quality="720", headers=None, progress=lambda _: None):
        self.http, self.directory, self.quality = http, Path(directory), quality
        self.headers, self.progress = playback_headers(headers), progress
        self.total = 0
        self._lock = threading.Lock()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _resource(self, url, path, byte_range=None, maximum=None):
        reserve = 128 * 1024**2
        free = shutil.disk_usage(self.directory).free
        # Leave enough free space for ffmpeg's MP4 output in addition to HLS input.
        budget = min(MAX_VIDEO - self.total, (free - reserve) // 2)
        if maximum is not None:
            budget = min(budget, maximum)
        if budget <= 0:
            raise SourceError("В бесплатной сессии закончилось место. Уже сохранённые серии останутся в Drive.")
        size = self.http.download(url, path, headers=self.headers, byte_range=byte_range, maximum=budget)
        with self._lock:
            self.total += size
            if self.total > MAX_VIDEO:
                raise SourceError('Размер видео превысил лимит свободного диска.')
        return size

    def materialize(self, url, name="video", depth=0):
        if depth > 4:
            raise SourceError("Слишком много вложенных HLS-плейлистов.")
        text, final, _ = self.http.document(url, headers=self.headers)
        if not text.lstrip().startswith("#EXTM3U"):
            raise SourceError("Вместо HLS источник вернул другой документ.")
        playlist = m3u8.loads(text, uri=final)
        if playlist.session_keys:
            raise SourceError("Сессионные ключи и DRM-плейлисты не поддерживаются.")
        if playlist.is_variant:
            selected = choose_variant(playlist.playlists, self.quality)
            video = self.materialize(urljoin(final, selected.uri), name, depth + 1)
            group = selected.stream_info.audio
            alternatives = [media for media in playlist.media if media.type == "AUDIO" and media.group_id == group and media.uri]
            if alternatives:
                audio = next((media for media in alternatives if media.default == "YES"), alternatives[0])
                audio_files = self.materialize(urljoin(final, audio.uri), name + "-audio", depth + 1)
                return [video[0], audio_files[0]]
            return video
        if not playlist.is_endlist or not playlist.segments:
            raise SourceError("Нужна законченная серия. Прямые эфиры и незавершённые HLS не скачиваются.")
        if len(playlist.segments) > 20000:
            raise SourceError("В одном эпизоде слишком много HLS-сегментов.")
        target = self.directory / name
        target.mkdir(exist_ok=True)
        offsets, maps, keys = {}, {}, {}
        # Capture absolute URIs before mutating shared Key/InitializationSection objects.
        resources = [(segment, urljoin(final, segment.uri),
                      urljoin(final, segment.init_section.uri) if segment.init_section else None,
                      urljoin(final, segment.key.uri) if segment.key and segment.key.uri else None,
                      segment.init_section.byterange if segment.init_section else None)
                     for segment in playlist.segments]
        downloads=[]
        for index, (segment, segment_url, map_url, key_url, map_range) in enumerate(resources):
            key = segment.key
            if key and key.method != "NONE":
                if key.method != "AES-128" or key.keyformat not in (None, "identity") or not key_url:
                    raise SourceError("DRM и SAMPLE-AES не поддерживаются.")
                if key_url not in keys:
                    filename = f"key-{len(keys)}.bin"
                    if self._resource(key_url, target / filename, maximum=16) != 16:
                        raise SourceError("Некорректный открытый ключ AES-128 HLS.")
                    keys[key_url] = filename
                key.uri = keys[key_url]
            initialization = segment.init_section
            if initialization:
                map_id = (map_url, map_range)
                if map_id not in maps:
                    filename = f"map-{len(maps)}.mp4"
                    self._resource(map_url, target / filename,
                                   byte_range(map_range, map_url, offsets))
                    maps[map_id] = filename
                initialization.uri = maps[map_id]
                initialization.byterange = None
            extension = Path(urlsplit(segment_url).path).suffix.lower()
            if extension not in {".ts", ".m4s", ".mp4", ".aac", ".mp3", ".ac3", ".ec3", ".m4a"}:
                extension = ".m4s" if initialization else ".ts"
            filename = f"segment-{index:06d}{extension}"
            downloads.append((segment_url, target / filename, byte_range(segment.byterange, segment_url, offsets)))
            segment.uri, segment.byterange = filename, None
        # Each worker owns its requests.Session. No shared cookies/transports.
        local=threading.local();clients=[];client_lock=threading.Lock();saved=0
        def download(entry):
            nonlocal saved
            if hasattr(self.http,'fork'):
                if not hasattr(local,'http'):
                    local.http=self.http.fork()
                    with client_lock:clients.append(local.http)
                client=local.http
            else:client=self.http
            url,path,range_=entry
            with self._lock:
                budget=min(MAX_VIDEO-self.total,(shutil.disk_usage(self.directory).free-128*1024**2)//2)
            if budget<=0:raise SourceError('Недостаточно свободного диска для серии.')
            size=client.download(url,path,headers=self.headers,byte_range=range_,maximum=budget)
            with self._lock:
                self.total+=size;saved+=1
                if self.total>MAX_VIDEO:raise SourceError('Превышен лимит размера видео.')
                if saved%10==0 or saved==len(downloads):self.progress({'phase':'downloading','loaded':saved,'total':len(downloads),'downloadedBytes':self.total})
        try:
            with ThreadPoolExecutor(max_workers=4 if hasattr(self.http,'fork') else 1) as executor:
                # map submits references only; media remains on disk, not in RAM.
                for _ in executor.map(download,downloads):pass
        finally:
            for client in clients:client.close()
        manifest = target / "local.m3u8"
        manifest.write_text(playlist.dumps(), encoding="utf-8")
        return [manifest]


def verify_video(path, *, run=subprocess.run):
    result = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration,size",
                  "-of", "json", str(path)], capture_output=True, text=True, timeout=60, check=False)
    try:
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        valid = (result.returncode == 0 and int(info["format"]["size"]) > 0
                 and math.isfinite(duration) and duration > 0
                 and any(stream.get("codec_type") == "video" for stream in info.get("streams", [])))
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise SourceError("Не удалось проверить готовое видео. Оно не будет добавлено в библиотеку.")
    return info


def download_episode(stream, directory, *, http, quality="720", progress=lambda _: None, run=subprocess.run):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    progress({"phase": "downloading", "loaded": 0, "total": 0})
    kind, headers = stream.get("type"), playback_headers(stream.get("headers"))
    if kind == "hls":
        inputs = HlsDownload(http, directory, quality, headers, progress).materialize(stream["url"])
    elif kind == "mp4":
        path = directory / "source.mp4"
        maximum = min(MAX_VIDEO, (shutil.disk_usage(directory).free - 128 * 1024**2) // 2)
        if maximum <= 0:
            raise SourceError("Недостаточно места для видео в сессии Colab.")
        http.download(stream["url"], path, headers=headers, maximum=maximum)
        inputs = [path]
    else:
        raise SourceError("Поддерживаются публичные MP4 и HLS.")
    output = directory / "episode.mp4"
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    for path in inputs:
        args += ["-protocol_whitelist", "file,crypto"]
        if path.suffix == ".m3u8":
            args += ["-allowed_extensions", "ALL"]
        args += ["-i", str(path)]
    args += ["-map", "0:v:0", "-map", "1:a:0" if len(inputs) > 1 else "0:a:0?",
             "-c", "copy", "-movflags", "+faststart", str(output)]
    progress({"phase": "assembling", "loaded": 0, "total": 0})
    result = run(args, capture_output=True, text=True, timeout=900, check=False)
    if result.returncode:
        raise SourceError("ffmpeg не смог собрать MP4 из этого потока. Готовые серии можно продолжить отдельным запуском.")
    verify_video(output, run=run)
    return output


def preview_frame(path):
    """Decode a single real episode frame. Never transcode the actual video."""
    try:
        info = verify_video(path)
        point = float(info['format']['duration']) * .35
        result = subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(round(point,2)),'-i',str(path),
                                 '-frames:v','1','-vf',"scale='min(1280,iw)':-2",'-q:v','4','-threads','1','-f','image2pipe','-vcodec','mjpeg','-'],
                                capture_output=True,timeout=25,check=False)
        image=result.stdout
        return image if result.returncode==0 and image.startswith(b'\xff\xd8\xff') and len(image)<=500000 else None
    except (subprocess.SubprocessError,SourceError,ValueError,KeyError):return None
