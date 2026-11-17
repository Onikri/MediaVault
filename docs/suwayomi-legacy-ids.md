# Старые числовые ID Suwayomi

Старые ссылки MediaVault на мангу из Suwayomi имеют вид
`<PUBLIC_URL>/__manga/suwayomi/m/<тайтл>[/c/<глава>[/p/<страница>]]`.
`<тайтл>` — строка `MANGA.ID` в базе H2 Suwayomi, `<глава>` — `CHAPTER.SOURCE_ORDER`
(REST-поле `index`), а не номер главы. Вне этой базы такие числа ничего не значат.
ID источника (`suwayomi:<sourceId>`) — стабильный хэш расширения Tachiyomi; прямые
адаптеры используют тот же ID, поэтому его не переносят.

## Где хранятся старые ссылки

| Хранилище | Что там | Как переносится |
| --- | --- | --- |
| `manga-discovery.sqlite` → `catalog_titles.metadata.url` | ссылка на тайтл из каталога (`source_url` уже публичный) | переписывается на прямой адрес тайтла |
| `manga-discovery.sqlite` → `titles` (кэш поиска) | `url`/`sourceURL` тайтла | переписывается так же; ID строки не меняется |
| `places.sqlite`, ключи `m:online:<ссылка главы>` | место чтения (страница главы) | добавляется копия под точным URL эпизода прямой читалки; старое место остаётся |
| `places.sqlite`, `h:manga:…:suwayomi:<sid>:<id>` | строка истории, маршрут `#watch=` | не меняется: открывается через снимок тайтла и резолвер |
| `tasks.sqlite` → задания импорта (`job.sources`) | ссылка тайтла | только отчёт; задания меняются лишь через API сервиса |
| `tasks.sqlite` → `title-share:*` | главы общих ссылок | только отчёт; открываются через резолвер |
| `catalogue_jobs` (`bridge-detail`, поле `manga`) | дозагрузка карточки | только отчёт; при живом адаптере задание уже идёт напрямую по `row.sourceUrl` |
| браузеры (localStorage) | прогресс, история, снимки тайтлов | сервер не видит; открываются через резолвер, места приходят синхронизацией |

Обложки: каталог хранит только публичные `https://` обложки; внутренний
`/api/v1/manga/<id>/thumbnail` Suwayomi наружу никогда не отдавался.

## Карта ID

`/data/suwayomi-legacy-map.sqlite` (таблицы `sources`, `manga`, `chapters`, `meta.exports`)
строит `deploy/oracle/export-suwayomi-legacy-map.sh`:

```bash
sudo bash export-suwayomi-legacy-map.sh /path/to/server/suwayomi_legacy.py
```

Скрипт копирует файл H2, читает копию jar-файлом Suwayomi в контейнере без сети,
один раз читает `/source/list` (базовые адреса), сливает строки в карту (ничего не
удаляет) и кладёт копию в `/srv/mediavault/backups/suwayomi-legacy-map-<время>/`.
Повторять экспорт можно, пока Suwayomi работает; после его остановки карта — единственный источник.

## Резолвер

`suwayomi_legacy.resolve(manga, chapter)` отвечает на REST-вызовы моста из карты
(`MapClient`) и использует те же правила `suwayomi_bridge.native_reader_url`, что и
живой мост. `suwayomi_bridge.parse_reference/inspect/page_image` пробуют его до Suwayomi;
при сбое прямой читалки остаётся Suwayomi (пока он есть). Источник без активного
адаптера даёт «пока не подключён напрямую» и начинает открываться сам, когда его ID
попадает в `server/manga_native_activation.json`.

## Миграция

```bash
docker exec -i -w /app oracle-importer-1 python suwayomi_legacy_migrate.py --data /data            # отчёт
docker exec -i -w /app oracle-importer-1 python suwayomi_legacy_migrate.py --data /data --apply --online --report /data/.codex-local/legacy-migration.json
```

Идемпотентна: повторный запуск ничего не меняет. Каталог переписывается без сети;
`--online` читает список эпизодов каждого тайтла из прогресса один раз, чтобы ключ
места совпал с URL эпизода. Причины «оставлено»: `no-direct-reader` (адаптер не
активирован), `needs-online-lookup` (Madara хранит только post ID — откроется по
ссылке онлайн), `unknown-title`/`unknown-chapter` (нет в карте), `title-unavailable-now`.
После активации новых профилей миграцию запускают снова.
