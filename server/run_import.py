"""One-episode-at-a-time public-source → server → encrypted Drive import."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from media_download import download_episode, pick_stream,video_height,expand_stream_qualities
from source_parser import Resolver, SourceError, episode_number, public_url


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
        allowed |= {"section", "metadata", "entries", "dub", "provider", "translation"}
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
    from manga_sources import chapter_ranges
    selected = None if section=='manga' else episode_selection(value.get('episodes','all'))
    chapters = chapter_ranges(value.get('episodes','all')) if section=='manga' else None
    entries = value.get("entries") or []
    if not isinstance(entries, list) or len(entries) > 1000:
        raise SourceError("Слишком много файлов в одном задании.")
    prepared = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"number", "url", "title", "season", "description"}:
            raise SourceError("Некорректный список опубликованных серий.")
        number, entry_season = entry.get("number"), entry.get("season", season)
        if section=='manga':
            from manga_sources import chapter_number
            number=chapter_number(number)
        elif isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10000:
            raise SourceError("Некорректный номер опубликованной серии.")
        if isinstance(entry_season, bool) or not isinstance(entry_season, int) or not 1 <= entry_season <= 1000:
            raise SourceError("Некорректный сезон серии.")
        prepared.append({"number": number, "url": public_url(entry.get("url"), resolve_dns=False),
                         "title": str(entry.get("title", ""))[:300], "description":str(entry.get("description", ""))[:6000], "season": entry_season})
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict) or len(json.dumps(metadata).encode()) > 100000:
        raise SourceError("Слишком большое описание тайтла.")
    translation=value.get('translation') or {}
    if not isinstance(translation,dict) or set(translation)-{'name','kind','language','player','variantId'}:
        raise SourceError('Некорректный перевод.')
    if translation:
        if translation.get('kind') not in ({'manga'} if section=='manga' else {'voice','subtitles'}) or any(not isinstance(v,str) or len(v)>180 for v in translation.values()):
            raise SourceError('Некорректные параметры перевода.')
    return {"version":value['version'],"library_id": library, "sources": sources, "collection": collection,
            "quality": quality, "selected": selected, "chapters":chapters,"season": int(season), "section": section,
            "metadata": metadata, "entries": prepared, "translation":translation, "dub": str(value.get("dub", ""))[:120]}


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


def run_job(value, vault, *, resolver=None, downloader=download_episode, log=print, progress=None, cancelled=None, temporary_dir=None, start_index=0, max_files=None, on_saved=None):
    job = validate_job(value)
    if getattr(vault, "library_id", None) != job["library_id"]:
        raise SourceError("Открытая библиотека не совпадает с заданием.")
    own_resolver = resolver is None
    resolver = resolver or Resolver()
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
            label = f"Серия {number}" if number is not None else f"Видео {index}"
            emit({"current": index, "total": len(plans), "episode": number, "title": collection,
                  "phase": "preparing", **result})
            category = "manga" if job["section"] == "manga" else "book" if job["section"] in {"ranobe", "book"} else "video"
            # Check before contacting the player, because its signed links expire.
            if vault.completed(identity, collection=collection, episode=number, category=category):
                result["skipped"] += 1
                log(f"[{index}/{len(plans)}] {label}: уже в Drive, пропускаю.")
                continue
            log(f"[{index}/{len(plans)}] {label}: скачивание на сервер импорта.")
            # Every episode gets its own temporary directory; nothing accumulates for a season.
            with tempfile.TemporaryDirectory(prefix="mediavault-episode-", dir=temporary_dir) as temporary:
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
                        emit(event)
                        phase = event.get("phase")
                        if phase != last_phase[0]:
                            text = {"downloading": "скачивание", "assembling": "сборка MP4",
                                    "uploading": "шифрование и запись в Drive", "done": "сохранено"}.get(phase)
                            if text:
                                log(f"  {label}: {text}.")
                            last_phase[0] = phase
                    if category == "manga":
                        path = download_chapter(entry["url"], temporary, resolver.http,progress=report,quality=job["quality"])
                        page = type("Chapter", (), {"title": entry["title"]})()
                    elif category == "book":
                        path = download_text(entry["url"], temporary, resolver.http)
                        page = type("Chapter", (), {"title": entry["title"]})()
                    else:
                        parent=job['sources'][0] if (urlsplit(entry['url']).hostname or '').endswith(('.stravers.live','.thealloha.club','.alloha.tv')) else None
                        page = resolver.resolve(entry["url"],referer=parent) if parent else resolver.resolve(entry["url"])
                        streams=expand_stream_qualities(page.streams,resolver.http)
                        stream = pick_stream(streams, job["quality"])
                        path = downloader(stream, temporary, http=resolver.http, quality=job["quality"], progress=report)
                except SourceError as error:
                    result["failed"] += 1
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
                options = {"metadata": job["metadata"], "dub": job["dub"]} if job["metadata"] or job["dub"] else {}
                if job.get('translation'):options['translation']=job['translation']
                from title_extras import russian
                episode_title=russian(entry.get('title'))
                if episode_title and not re.fullmatch(r'(?:Серия|Эпизод)\s*\d+',episode_title,re.I):options['episode_title']=episode_title
                if russian(entry.get('description')):options['episode_description']=russian(entry['description'])
                if category == 'video':
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
                saved_item=vault.upload_file(path, name=name, category=category, collection=collection,
                                  episode=number, source_identity=identity, mime=mime, progress=report,
                                  section=job["section"], part=f"{'Том' if category != 'video' else 'Сезон'} {season}", season=season, **options)
                result["saved"] += 1
                emit({**result, "phase": "episode_done"})
                if on_saved:on_saved(saved_item)
        log(f"Готово: сохранено {result['saved']}, уже были в Drive {result['skipped']}, недоступны {result['failed']}.")
        return {**result,'cursor':cursor,'remaining':cursor<len(plans),'total':len(plans)} if max_files else result
    finally:
        if own_resolver:
            resolver.http.close()


def download_chapter(url, temporary, http,progress=lambda _:None,quality='best'):
    from manga_download import download_chapter as download
    return download(url,temporary,http,progress=progress,quality=quality)


def download_text(url, temporary, http):
    from bs4 import BeautifulSoup
    text, _, _ = http.document(url)
    soup = BeautifulSoup(text, "html.parser")
    article = soup.select_one(".chapter-content, .text-content, article")
    if not article or len(article.get_text(strip=True)) < 100:
        raise SourceError("Публичный текст главы не найден.")
    for tag in article.select("script, style, nav, form"):
        tag.decompose()
    path = Path(temporary) / "chapter.txt"
    path.write_text(article.get_text("\n", strip=True), encoding="utf-8")
    return path
