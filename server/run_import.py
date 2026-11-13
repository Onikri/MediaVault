"""One-episode-at-a-time public-source → server → encrypted Drive import."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from media_download import download_episode, pick_stream,video_height,expand_stream_qualities
from source_parser import Resolver, SourceAccessError, SourceError, episode_number, is_alloha_player, public_url


def episode_selection(value):
    value = str(value or "all").strip().lower()
    if value in {"all", "все", ""}:
        return None
    numbers = set()
    for part in value.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not match:
            raise SourceError("Серии указываются как all, 1-12 или 1,3,5-8.")
        first, last = int(match[1]), int(match[2] or match[1])
        if first < 1 or last < first or last > 10000:
            raise SourceError("Некорректный диапазон серий.")
        numbers.update(range(first, last + 1))
    return numbers


def validate_job(value):
    if not isinstance(value, dict) or value.get("version") not in {1, 2, 3}:
        raise SourceError("Неизвестная версия задания MediaVault.")
    # Reject accidental pasted credentials rather than saving or forwarding them.
    allowed = {"version", "library_id", "sources", "collection", "episodes", "quality", "resume", "season"}
    if value["version"] >= 2:
        allowed |= {"section", "metadata", "entries", "dub", "provider", "translation", "alloha_mode", "output", "voice", "render"}
    if set(value) - allowed:
        raise SourceError("В задании есть лишние поля. Скопируй новое задание с сайта.")
    library = value.get("library_id", "")
    if not isinstance(library, str) or not re.fullmatch(r"[\w-]{5,256}", library, flags=re.ASCII):
        raise SourceError("В задании отсутствует ID открытой библиотеки.")
    urls = value.get("sources")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 200:
        raise SourceError("В задании должно быть от 1 до 200 ссылок.")
    sources = list(dict.fromkeys(public_url(url, resolve_dns=False) for url in urls))
    quality = str(value.get("quality", "best" if value['version']>=3 else "720"))
    if quality!='best' and (not quality.isdigit() or not 1<=int(quality)<=8640):
        raise SourceError("Некорректное качество.")
    if quality!='best':quality=str(int(quality))
    collection = str(value.get("collection", "")).strip()[:180]
    season = value.get("season", 1)
    if isinstance(season, bool) or not str(season).isdigit() or not 1 <= int(season) <= 1000:
        raise SourceError("Укажи номер сезона от 1 до 1000.")
    if len(sources) > 1 and not collection:
        raise SourceError("Укажи общее название аниме для списка серий.")
    section = value.get("section", "anime")
    if section not in {"anime", "video", "manga", "ranobe", "book"}:
        raise SourceError("Неизвестный раздел импорта.")
    alloha_mode = value.get('alloha_mode')
    if alloha_mode is not None and alloha_mode not in ('bnsi', 'browser'):
        raise SourceError('Неизвестный режим подключения Alloha.')
    from manga_sources import chapter_ranges
    selected = None if section=='manga' else episode_selection(value.get('episodes','all'))
    chapters = chapter_ranges(value.get('episodes','all')) if section=='manga' else None
    entries = value.get("entries") or []
    if not isinstance(entries, list) or len(entries) > 1000:
        raise SourceError("Слишком много файлов в одном задании.")
    prepared = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"number", "url", "title", "season", "description", "export"}:
            raise SourceError("Некорректный список опубликованных серий.")
        export = entry.get("export")
        if export is not None and (section == 'manga' or not isinstance(export, str) or not re.fullmatch(r"[0-9a-f]{32}", export)):
            raise SourceError("Некорректная серия, переданная из браузера.")
        number, entry_season = entry.get("number"), entry.get("season", season)
        if section=='manga':
            from manga_sources import chapter_number
            number=chapter_number(number)
        elif isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10000:
            raise SourceError("Некорректный номер опубликованной серии.")
        if isinstance(entry_season, bool) or not isinstance(entry_season, int) or not 1 <= entry_season <= 1000:
            raise SourceError("Некорректный сезон серии.")
        prepared.append({"number": number, "url": public_url(entry.get("url"), resolve_dns=False),
                         "title": str(entry.get("title", ""))[:300], "description":str(entry.get("description", ""))[:6000], "season": entry_season,
                         **({"export": export} if export else {})})
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict) or len(json.dumps(metadata).encode()) > 100000:
        raise SourceError("Слишком большое описание тайтла.")
    translation=value.get('translation') or {}
    if not isinstance(translation,dict) or set(translation)-{'name','kind','language','player','variantId'}:
        raise SourceError('Некорректный перевод.')
    if translation:
        if translation.get('kind') not in ({'manga'} if section=='manga' else {'voice','subtitles'}) or any(not isinstance(v,str) or len(v)>180 for v in translation.values()):
            raise SourceError('Некорректные параметры перевода.')
    output = value.get("output", "text")
    voice = value.get("voice") or None
    if section in {"ranobe", "book"}:
        if output not in {"text", "audio", "both"}:
            raise SourceError("Выбери текст, аудиокнигу или оба варианта.")
        voice = narration_direction(voice) if output != "text" else None
    elif "output" in value or "voice" in value:
        raise SourceError("Аудиокнига доступна только для ранобэ и книг.")
    render = value.get("render") or None
    if render is not None:
        if section != "manga":
            raise SourceError("Перевод страниц доступен только для манги.")
        from manga_export import Translation
        try:
            render = Translation.model_validate(render).model_dump()
        except Exception:
            raise SourceError("Некорректные настройки перевода манги.") from None
    return {"version":value['version'],"library_id": library, "sources": sources, "collection": collection,
            "quality": quality, "selected": selected, "chapters":chapters,"season": int(season), "section": section,
            "metadata": metadata, "entries": prepared, "translation":translation, "dub": str(value.get("dub", ""))[:120],
            "alloha_mode": alloha_mode, "output": output, "voice": voice, "render": render}


ROLE_MODELS = {"gemini-3.5-flash-lite", "gemma-4-26b-a4b-it", "gemma-4-31b-it"}
BIBLE_MODELS = {"gemini-3.5-flash-lite", "gemma-4-31b-it"}


def narration_direction(value):
    """What the owner's reader knows about the book's voices (src/tts/chapter-script.js
    bookDirection): narrator choice, pace, role models, the listener's voice choices
    and the title bible. The VM director voices the book the same way."""
    from gemini_voice import VOICES
    if not isinstance(value, dict) or set(value) - {"prefs", "saved", "cast", "bible", "language"}:
        raise SourceError("Не хватает настроек озвучки. Открой окно сохранения заново.")
    if len(json.dumps(value, ensure_ascii=False).encode()) > 160000:
        raise SourceError("Настройки озвучки книги слишком большие.")
    prefs = value.get("prefs") or {}
    if not isinstance(prefs, dict) or set(prefs) - {"geminiNarrator", "narrator", "pace", "roles", "rolesModel", "bibleModel"}:
        raise SourceError("Некорректные настройки озвучки.")
    narrator = prefs.get("geminiNarrator", "auto")
    pace = prefs.get("pace", 1)
    if (narrator not in VOICES | {"auto", "m", "f"} or isinstance(pace, bool) or not isinstance(pace, (int, float)) or not .5 <= pace <= 2
            or prefs.get("rolesModel", "gemini-3.5-flash-lite") not in ROLE_MODELS or prefs.get("bibleModel", "gemini-3.5-flash-lite") not in BIBLE_MODELS
            or not isinstance(prefs.get("roles", True), bool) or not isinstance(prefs.get("narrator", "auto"), str) or len(prefs.get("narrator", "auto")) > 40):
        raise SourceError("Некорректные настройки озвучки.")
    for key in ("saved", "cast"):
        if not isinstance(value.get(key) or {}, dict):
            raise SourceError("Некорректный каст голосов.")
    if value.get("bible") is not None and not isinstance(value["bible"], dict):
        raise SourceError("Некорректная карточка книги для озвучки.")
    language = value.get("language", "ru")
    if language not in {"ru", "uk"}:
        raise SourceError("Аудиокнига озвучивается на русском или украинском.")
    return {"prefs": {"geminiNarrator": narrator, "narrator": prefs.get("narrator", "auto"), "pace": pace, "roles": prefs.get("roles", True),
                      "rolesModel": prefs.get("rolesModel", "gemini-3.5-flash-lite"), "bibleModel": prefs.get("bibleModel", "gemini-3.5-flash-lite")},
            "saved": value.get("saved") or {}, "cast": value.get("cast") or {}, "bible": value.get("bible"), "language": language}


def source_identity(url):
    """Keep logical episode/dub identity; remove rotating CDN signatures."""
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query)
             if key.lower() in {"episode", "season", "translation", "videoid", "id", "oid", "dubbing", "mv_translation", "mv_player", "titleid", "no", "title_no", "episode_no", "lang"}]
    stable = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
                        urlencode(sorted(query)), ""))
    # A non-URL prefix keeps vault_drive from dropping meaningful episode queries.
    return "public-player-v1:" + stable


def plan_sources(job, resolver):
    seen, plans, discovered = set(), [], set()
    def wanted(number):
        if job['section']=='manga':
            from manga_sources import selected
            return selected(number,job.get('chapters'))
        return job['selected'] is None or number in job['selected']
    if job.get("entries"):
        for entry in job["entries"]:
            if not wanted(entry['number']):
                continue
            identity = source_identity(entry["url"])
            key = (identity, entry["season"], entry["number"])
            if key not in seen:
                plans.append({**entry, "identity": identity, "collection": job["collection"] or "Импорт"})
                seen.add(key)
        if not plans:
            raise SourceError("Выбранные серии отсутствуют в опубликованном списке.")
        return plans
    for index, source in enumerate(job["sources"], 1):
        if job['section']=='manga':
            from manga_sources import inspect
            from types import SimpleNamespace
            value=inspect(source,http=resolver.http)
            if not value['episodes']:raise SourceError('В этой манге не найдены открытые главы для импорта.')
            page=SimpleNamespace(episodes=value['episodes'],title=value['title'],streams=[],players=[])
        else:page = resolver.inspect(source)
        episodes = page.episodes
        # A title page may embed a serial player with actual published episode options.
        if not episodes and not page.streams:
            for embed in page.players:
                try:
                    embedded = resolver.inspect(embed)
                except SourceError:
                    continue
                if embedded.episodes:
                    episodes = embedded.episodes
                    break
        if not episodes:
            number = episode_number(source)
            # Ordered explicit links are the user's episode list, not invented site episodes.
            if number is None and len(job["sources"]) > 1:
                number = index
            episodes = [{"number": number, "title": page.title, "url": source}]
        for episode in episodes:
            number = episode.get("number")
            if number:
                discovered.add(number)
            if not wanted(number):
                continue
            identity = source_identity(episode["url"])
            if identity in seen:
                continue
            seen.add(identity)
            plans.append({"number": number, "title": episode.get("title") or page.title,
                          "url": episode["url"], "identity": identity,
                          "season":episode.get('season',job['season']) if job['section']=='manga' else job['season'],"collection": job["collection"] or page.title[:180] or "Импорт"})
    if not plans:
        raise SourceError("Нужные опубликованные серии не найдены. Можно вставить отдельные ссылки серий списком.")
    return plans


def video_import_source(job, entry, http):
    url = entry['url']
    parent = job['sources'][0] if is_alloha_player(url) else None
    # Older queued imports for this film still carry the legacy embed.
    # Resolve the exact same published dub while keeping the saved fingerprint.
    legacy = urlsplit(url)
    if (parent and urlsplit(parent).hostname == 'yummyanime.tv'
            and urlsplit(parent).path == '/4660-chelovek-benzopila-reze-s7.html'
            and legacy.hostname == 'absciss.thealloha.club'
            and dict(parse_qsl(legacy.query)).get('translation') == '66'
            and job['dub'] == 'Дублированный'):
        from yummy_anime_source import REZE_PAGE, inspect
        published = inspect(REZE_PAGE, http)
        if published['ids'].get('mal') == 57555:
            for dub in published['dubs']:
                if dub['name'] == job['dub'] and dict(parse_qsl(urlsplit(dub['url']).query)).get('translation') == '66':
                    return dub['url'], published['url']
    return url, parent


def run_job(value, vault, *, resolver=None, downloader=download_episode, log=print, progress=None, cancelled=None, temporary_dir=None, start_index=0, max_files=None, on_saved=None, alloha_downloader=None, alloha_cache=None, alloha_streamer=None, staged_source=None, audiobook=None, manga_translator=None):
    job = validate_job(value)
    if getattr(vault, "library_id", None) != job["library_id"]:
        raise SourceError("Открытая библиотека не совпадает с заданием.")
    own_resolver = resolver is None
    resolver = resolver or Resolver(native_alloha=alloha_downloader is not None or alloha_streamer is not None)
    result = {"saved": 0, "skipped": 0, "failed": 0}
    emit = progress or (lambda event: None)
    try:
        plans = plan_sources(job, resolver)
        log(f"Найдено серий для задания: {len(plans)}. Обрабатываем по одной.")
        found = {entry["number"] for entry in plans if entry["number"] is not None}
        if job["selected"] is not None and job["selected"] - found:
            log("Некоторые указанные серии не опубликованы в найденных ссылках; они не будут выдуманы или загружены.")
        cursor = max(0,int(start_index))
        selected_plans=plans[cursor:cursor+max_files] if max_files else plans[cursor:]
        for index, entry in enumerate(selected_plans, cursor+1):
            if cancelled and cancelled():
                break
            cursor=index
            number, collection = entry["number"], entry["collection"]
            season = entry.get("season", job["season"])
            identity = entry["identity"] + (':translation=' + __import__('hashlib').sha256(json.dumps(job['translation'],sort_keys=True).encode()).hexdigest() if job.get('translation') else '') + (f":season={season}" if season != 1 else "")
            if job["dub"]:
                identity += ":dub=" + job["dub"]
            # Old queued jobs keep their exact fingerprints and recovery behavior.
            # New jobs may intentionally import another quality of the same dub.
            if job['version']>=3:identity+=':quality='+job['quality']
            if job.get('render'):identity+=':render='+__import__('hashlib').sha256(json.dumps(job['render'],sort_keys=True).encode()).hexdigest()
            label = f"Серия {number}" if number is not None else f"Видео {index}"
            emit({"current": index, "total": len(plans), "episode": number, "title": collection,
                  "phase": "preparing", "operation": "Проверяем, есть ли этот файл в Drive", **result})
            category = "manga" if job["section"] == "manga" else "book" if job["section"] in {"ranobe", "book"} else "video"
            if category == "book" and job.get("output", "text") != "text":
                outcome = save_book_chapter(job, entry, vault, identity=identity, collection=collection, number=number, season=season,
                                            label=f"[{index}/{len(plans)}] {label}", http=resolver.http,
                                            emit=lambda event, index=index, number=number, collection=collection: emit({"current": index, "total": len(plans), "episode": number, "title": collection, **event}),
                                            log=log, cancelled=cancelled, temporary_dir=temporary_dir, audiobook=audiobook, on_saved=on_saved)
                result[outcome] += 1
                if outcome == "saved":
                    emit({**result, "phase": "episode_done"})
                if cancelled and cancelled():
                    break
                continue
            # Check before contacting the player, because its signed links expire.
            if vault.completed(identity, collection=collection, episode=number, category=category):
                result["skipped"] += 1
                log(f"[{index}/{len(plans)}] {label}: уже в Drive, пропускаю.")
                continue
            log(f"[{index}/{len(plans)}] {label}: скачивание на сервер импорта.")
            # Every episode gets its own temporary directory; nothing accumulates for a season.
            with tempfile.TemporaryDirectory(prefix="mediavault-episode-", dir=temporary_dir) as temporary:
                streaming = None
                try:
                    last_phase = [None]
                    def report(event):
                        if cancelled and cancelled():
                            raise SourceError('Импорт отменён владельцем.')
                        event = dict(event)
                        if "total" in event:
                            event["bytesTotal"] = event.pop("total")
                        if "loaded" in event:
                            event["bytesLoaded"] = event.pop("loaded")
                        event.setdefault("operation", "")
                        emit(event)
                        phase = event.get("phase")
                        if phase != last_phase[0]:
                            text = {"downloading": "скачивание", "assembling": "сборка MP4",
                                    "uploading": "шифрование и запись в Drive", "done": "сохранено"}.get(phase)
                            if text:
                                log(f"  {label}: {text}.")
                            last_phase[0] = phase
                    if category == "manga" and job.get("render"):
                        # The VM translates the chapter with the reader's own renderer; it is then encrypted like any chapter.
                        if not manga_translator:
                            raise SourceError("Перевод манги в Google Диск выполняет только сервер импорта.")
                        path = manga_translator(entry, temporary, resolver.http, render=job["render"], quality=job["quality"],
                                                collection=collection, progress=report, cancelled=cancelled)
                        page = type("Chapter", (), {"title": entry["title"]})()
                    elif category == "manga":
                        path = download_chapter(entry["url"], temporary, resolver.http,progress=report,quality=job["quality"])
                        page = type("Chapter", (), {"title": entry["title"]})()
                    elif category == "book":
                        path = download_text(entry["url"], temporary, resolver.http)
                        page = type("Chapter", (), {"title": entry["title"]})()
                    elif entry.get("export"):
                        # The viewer's browser fetched this episode (CDN refuses servers) and the
                        # server already remuxed it: take that MP4 instead of contacting the CDN.
                        if not staged_source:
                            raise SourceError("Серию из браузера можно сохранить только на сервере импорта.")
                        emit({"operation": "Берём серию, собранную из браузера"})
                        try:
                            path = staged_source(entry["export"], temporary)
                        except SourceError:
                            raise
                        except Exception:
                            raise SourceError("Серия из браузера больше не лежит на сервере. Сохрани её заново.") from None
                    else:
                        emit({"operation": "Подключаемся к источнику видео"})
                        url, parent = video_import_source(job, entry, resolver.http)
                        for attempt in range(2):
                            try:
                                if attempt:
                                    resolver.http.refresh_playback = True
                                page = resolver.resolve(url,referer=parent) if parent else resolver.resolve(url)
                                native = next((s for s in page.streams if s.get('type') == 'alloha-native'), None)
                                if native and alloha_streamer:
                                    checkpoint = Path(alloha_cache) / __import__('hashlib').sha256((identity+collection).encode()).hexdigest() if alloha_cache else None
                                    streaming = alloha_streamer(native['url'], temporary, quality=job['quality'], progress=report,
                                                               cancelled=cancelled, checkpoint=checkpoint, referer=native.get('headers', {}).get('Referer') or parent,
                                                               **({'mode': job['alloha_mode']} if job['alloha_mode'] else {}))
                                    path = None
                                elif native and alloha_downloader:
                                    checkpoint = Path(alloha_cache) / __import__('hashlib').sha256((identity+collection).encode()).hexdigest() if alloha_cache else None
                                    path = alloha_downloader(native['url'], temporary, quality=job["quality"], progress=report,
                                                             cancelled=cancelled, checkpoint=checkpoint,
                                                             referer=native.get('headers', {}).get('Referer') or parent,
                                                             **({'mode': job['alloha_mode']} if job['alloha_mode'] else {}))
                                else:
                                    streams=expand_stream_qualities(page.streams,resolver.http)
                                    stream = pick_stream(streams, job["quality"])
                                    path = downloader(stream, temporary, http=resolver.http, quality=job["quality"], progress=report)
                                break
                            except SourceAccessError:
                                if attempt or urlsplit(url).hostname != 'alloha.yani.tv' or (cancelled and cancelled()):
                                    raise
                                emit({"operation": "Обновляем доступ к потоку Alloha"})
                            finally:
                                if attempt:
                                    resolver.http.refresh_playback = False
                except SourceError as error:
                    result["failed"] += 1
                    emit({"sourceError": re.sub(r'https?://\S+', '[ссылка]', str(error))[:400]})
                    log(f"  {label}: {error}")
                    continue
                except Exception as error:
                    if error.__class__.__module__.startswith("anime_dl_core"):
                        result["failed"] += 1
                        log(f"  {label}: плеер не отдал публичный поток. Повтори позже или используй другую ссылку.")
                        continue
                    raise
                # Drive/auth/quota errors stop immediately; prior completed episodes are preserved.
                if cancelled and cancelled():
                    break
                extension, mime = ("cbz", "application/vnd.comicbook+zip") if category == "manga" else ("txt", "text/plain") if category == "book" else ("mp4", "video/mp4")
                noun = "глава" if category in {"manga", "book"} else "серия"
                number_label=str(number).zfill(3) if isinstance(number,int) else str(number)
                name = (f"{collection} — {noun} {number_label}.{extension}" if number is not None
                        else (page.title or entry["title"] or collection)[:220] + "." + extension)
                options = file_options(job, entry)
                if category == 'video' and streaming is None:
                    height=video_height(path)
                    if height:options['quality']=height
                    from media_download import preview_frame,animated_preview
                    motion=animated_preview(path)
                    if motion:options['preview_motion']=motion
                    thumbnail = preview_frame(path)
                    if thumbnail: options['preview'] = thumbnail
                elif category=='manga':
                    from manga_download import chapter_preview
                    thumbnail=chapter_preview(path)
                    if thumbnail:options['preview']=thumbnail
                options.update(name=name, category=category, collection=collection,
                               episode=number, source_identity=identity, mime=mime, progress=report,
                               section=job["section"], part=f"{'Том' if category != 'video' else 'Сезон'} {season}",
                               season=season)
                saved_item = streaming.upload(vault, **options) if streaming else vault.upload_file(path, **options)
                if category == 'video' and (alloha_downloader or alloha_streamer) and alloha_cache:
                    from alloha_import import discard_checkpoint
                    discard_checkpoint(Path(alloha_cache) / __import__('hashlib').sha256((identity+collection).encode()).hexdigest(), Path(alloha_cache))
                result["saved"] += 1
                emit({**result, "phase": "episode_done"})
                if on_saved:on_saved(saved_item)
        log(f"Готово: сохранено {result['saved']}, уже были в Drive {result['skipped']}, недоступны {result['failed']}.")
        return {**result,'cursor':cursor,'remaining':cursor<len(plans),'total':len(plans)} if max_files else result
    finally:
        if own_resolver:
            resolver.http.close()


def file_options(job, entry):
    """Library fields shared by every file of an import: title card, dub, episode text."""
    options = {"metadata": job["metadata"], "dub": job["dub"]} if job["metadata"] or job["dub"] else {}
    if job.get('translation'):options['translation']=job['translation']
    from title_extras import russian
    episode_title=russian(entry.get('title'))
    if episode_title and not re.fullmatch(r'(?:Серия|Эпизод)\s*\d+',episode_title,re.I):options['episode_title']=episode_title
    if russian(entry.get('description')):options['episode_description']=russian(entry['description'])
    return options


def save_book_chapter(job, entry, vault, *, identity, collection, number, season, label, http, emit, log, cancelled, temporary_dir, audiobook, on_saved=None):
    """Text and/or audiobook of one ranobe/book chapter. Each output has its own
    fingerprint: a chapter whose text is already in Drive gets only its audio."""
    import hashlib
    from ranobe_audiobook import PhraseCache, encode_opus, script_rows, synthesize
    direction = job.get("voice") or {}
    # Another narrator, pace, role model or voice choice is another audiobook;
    # the bible and the cast grow while a book is voiced and do not count.
    voicing = {key: direction.get(key) for key in ("prefs", "saved", "language")}
    audio_identity = identity + ":audio=" + hashlib.sha256(json.dumps(voicing, sort_keys=True).encode()).hexdigest()
    outputs = {"text": ["text"], "audio": ["audio"], "both": ["text", "audio"]}[job["output"]]
    emit({"phase": "preparing", "operation": "Проверяем, есть ли эта глава в Drive"})
    wanted = [kind for kind in outputs if not vault.completed(identity if kind == "text" else audio_identity,
                                                                collection=collection, episode=number, category="book")]
    if not wanted:
        log(f"{label}: уже в Drive, пропускаю.")
        return "skipped"
    if "audio" in wanted and not audiobook:
        raise SourceError("Аудиокнигу в Google Диск собирает только сервер импорта.")

    def report(event):
        if cancelled and cancelled():
            raise SourceError("Импорт отменён владельцем.")
        event = dict(event)
        if "total" in event:
            event["bytesTotal"] = event.pop("total")
        if "loaded" in event:
            event["bytesLoaded"] = event.pop("loaded")
        event.setdefault("operation", "")
        emit(event)

    number_label = str(number).zfill(3) if isinstance(number, int) else str(number)
    base = f"{collection} — глава {number_label}" if number is not None else (entry["title"] or collection)[:220]
    part = f"Том {season}"
    with tempfile.TemporaryDirectory(prefix="mediavault-chapter-", dir=temporary_dir) as temporary:
        try:
            emit({"phase": "downloading", "operation": "Загружаем текст главы"})
            text = chapter_text(entry["url"], http)
        except SourceError as error:
            emit({"sourceError": re.sub(r'https?://\S+', '[ссылка]', str(error))[:400]})
            log(f"  {label}: {error}")
            return "failed"
        if "text" in wanted:
            path = Path(temporary) / "chapter.txt"
            path.write_bytes(text["file"].encode("utf-8"))
            options = file_options(job, entry)
            options.update(name=base + ".txt", category="book", collection=collection, episode=number, source_identity=identity,
                           mime="text/plain", progress=report, section=job["section"], part=part, season=season)
            saved = vault.upload_file(path, **options)
            if on_saved:
                on_saved(saved)
        if "audio" in wanted:
            metadata = job["metadata"]
            meta = {"title": str(metadata.get("title") or collection)[:300], "aliases": metadata.get("aliases") or [], "authors": metadata.get("authors") or [],
                    "description": re.sub(r"<[^>]+>", "", str(metadata.get("description") or ""))[:1200], "year": metadata.get("year"),
                    "kind": metadata.get("kind") or job["section"], "language": direction.get("language", "ru")}
            try:
                emit({"phase": "directing", "operation": "Режиссёр размечает роли и голоса главы"})
                rows = script_rows(audiobook["script"](text["paragraphs"], book_key=job["sources"][0], chapter_key=entry["url"],
                                                       meta=meta, direction=direction, cancelled=cancelled))
            except SourceError as error:
                emit({"sourceError": str(error)[:400]})
                log(f"  {label}: {error}")
                return "failed"
            if not rows:
                emit({"sourceError": "В главе нет текста для озвучки."})
                return "failed"
            directory = audiobook.get("cache_dir")
            cache = PhraseCache(directory) if directory else None
            try:
                pcm, phrases = synthesize(rows, language=direction.get("language", "ru"),
                                          keys=audiobook["keys"](), scope=job["library_id"], cache=cache, progress=report,
                                          cancelled=cancelled or (lambda: False),
                                          **({"speak_phrase": audiobook["speak"]} if audiobook.get("speak") else {}))
            except SourceError as error:
                emit({"sourceError": str(error)[:400]})
                log(f"  {label}: {error}")
                return "failed"
            emit({"phase": "assembling", "operation": "Собираем файл аудиокниги"})
            authors = ", ".join(str(value) for value in (job["metadata"].get("authors") or []) if value)[:300]
            path = (audiobook.get("encode") or encode_opus)(pcm, Path(temporary) / "chapter.opus", tags={
                "title": entry.get("title") or text["title"] or base, "album": collection, "artist": authors, "genre": "Audiobook",
                "track": str(number) if number is not None else "", "comment": "Синтезированная озвучка MediaVault: Gemini 2.5 Flash Native Audio"})
            options = file_options(job, entry)
            options.update(name=base + ".opus", category="book", collection=collection, episode=number, source_identity=audio_identity,
                           mime="audio/ogg", progress=report, section=job["section"], part=part, season=season)
            saved = vault.upload_file(path, **options)
            if cache:
                cache.forget(phrases)
            if on_saved:
                on_saved(saved)
    log(f"  {label}: сохранено ({' и '.join({'text': 'текст', 'audio': 'аудио'}[kind] for kind in wanted)}).")
    return "saved"


def translate_chapter(owner, entry, temporary, http, *, render, quality, collection, progress, cancelled=None):
    """One manga chapter translated on the VM (manga_export.produce, the reader's renderer) as a CBZ."""
    from types import SimpleNamespace
    from manga_export import Options, produce

    class Budget:
        maximum = 2 * 1024**3
        def check(self):
            if cancelled and cancelled():
                raise SourceError("Импорт отменён владельцем.")
    options = Options.model_validate({"mode": "translate", "format": "cbz", "name": (collection or "Манга")[:180],
                                      "chapters": [{"url": entry["url"], "number": float(entry["number"]), "volume": int(entry.get("season") or 1),
                                                    "title": str(entry.get("title") or "")[:200]}],
                                      "translation": render}).model_dump()
    task = SimpleNamespace(owner=owner, directory=Path(temporary), quality=quality, manga=options)
    return produce(task, http, Budget(), progress)


def download_chapter(url, temporary, http,progress=lambda _:None,quality='best'):
    from manga_download import download_chapter as download
    return download(url,temporary,http,progress=progress,quality=quality)


def download_text(url, temporary, http):
    path = Path(temporary) / "chapter.txt"
    path.write_bytes(chapter_text(url, http)["file"].encode("utf-8"))
    return path


def chapter_text(url, http):
    """{title, paragraphs, file} of one chapter.

    Ranobe and public-domain book chapters come through the same adapters as
    the online reader (RanobeHub, Zenko, Gutenberg, Wikisource…); any other
    page falls back to its main article text."""
    try:
        from ranobe_sources import chapter
        data = chapter(url)
    except SourceError as error:
        if 'другой книге' in str(error) or 'пуста' in str(error):
            raise
        data = None
    except Exception:
        data = None
    if data and data.get("paragraphs"):
        lines = [str(p.get("text", "") if isinstance(p, dict) else p).strip() for p in data["paragraphs"]]
        title = str(data.get("title") or "").strip()
        paragraphs = [line for line in lines if line]
        body = "\n\n".join(paragraphs)
        return {"title": title, "paragraphs": paragraphs, "file": (title + "\n\n" + body) if title else body}
    from bs4 import BeautifulSoup
    text, _, _ = http.document(url)
    soup = BeautifulSoup(text, "html.parser")
    article = soup.select_one(".chapter-content, .text-content, article")
    if not article or len(article.get_text(strip=True)) < 100:
        raise SourceError("Публичный текст главы не найден.")
    for tag in article.select("script, style, nav, form"):
        tag.decompose()
    text = article.get_text("\n", strip=True)
    return {"title": "", "paragraphs": [line.strip() for line in text.split("\n") if line.strip()], "file": text}
