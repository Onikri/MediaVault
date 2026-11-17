# Транспорт источников: маршруты, японский выход и Byparr

Все прямые адаптеры ходят в сеть через один клиент — `PublicHttp` из `server/source_parser.py`. Модуль `server/source_transport.py` решает для каждого запроса и каждого шага перенаправления, через какой выход его отправить и можно ли передать браузерную проверку решателю Byparr. Маршруты объявляются в настройках источника, а не в коде адаптера. Инфраструктурную сторону (японский шлюз и Byparr на Oracle) описывает [docs/source-network-services.md](source-network-services.md), её пишет агент A.

Логины и платные главы транспорт не обходит. Для них есть отдельные статусы.

## Как адаптер объявляет маршруты

Декларации лежат в `server/manga_source_transport.json` и выкатываются вместе с кодом. Ключ — ID источника Suwayomi, тот же, что `SOURCE_ID` адаптера.

```json
{
  "version": 1,
  "sources": {
    "3115293328774708452": {
      "name": "Sokuyomi",
      "routes": [
        {"hosts": ["cdn.sokuyomi.jp"], "operations": ["*"], "exit": "direct", "format": "image"},
        {"hosts": ["sokuyomi.jp"], "operations": ["*"], "exit": "japan"}
      ]
    },
    "1024627298672457456": {
      "name": "Manganato",
      "solverBudget": 45,
      "routes": [
        {"hosts": ["natomanga.com", "nelomanga.net", "manganato.gg"], "operations": ["*"],
         "exit": "direct", "solver": true, "format": "html"}
      ]
    }
  }
}
```

Поля правила:

| Поле | Значения | Смысл |
| --- | --- | --- |
| `hosts` | 1–32 домена | Домен совпадает сам и со всеми поддоменами: `sokuyomi.jp` покрывает `api.sokuyomi.jp`. IP-адреса и порты запрещены. |
| `operations` | `search`, `catalogue`, `details`, `chapters`, `pages`, `images`, `*` | Операция, для которой действует правило. По умолчанию `*`. |
| `exit` | `direct`, `japan` | `japan` идёт через японский шлюз, `direct` идёт напрямую с Oracle. |
| `solver` | `true` / `false` | Передавать ли распознанную браузерную проверку решателю. По умолчанию `false`. |
| `format` | `html`, `json`, `image`, `cbz`, `any` | Чего ждёт адаптер. HTML из Byparr допускается только для `html` и `any`. По умолчанию `any`. |

Поле источника `solverBudget` задаёт бюджет запроса в секундах (0–75) для поиска и каталога источника с решателем. Без него берётся 45 секунд.

Правила проверяются по порядку, срабатывает первое совпавшее. Поэтому частное правило ставится выше общего: CDN `cdn.sokuyomi.jp` идёт напрямую, а остальной `sokuyomi.jp` — через Японию. Так же разводятся операции на одном домене: каталог LINE через Японию, картинки напрямую.

Если для источника нет декларации или запрос не совпал ни с одним правилом, работает прежняя маршрутизация по `action`: `Route(japan=True)` в `manga_ninth_routes.py`, издатели Comici/GigaViewer, SpeedBinb, Publus. Декларация имеет приоритет: правило `direct` снимает старый японский прокси.

Администратор может заменить декларацию источника без пересборки файлом `/data/manga-source-transport.json` того же формата. Источник из этого файла заменяется целиком. Файл с ошибкой игнорируется, чтобы не отключить все источники.

Файл проверяется строго: неизвестное поле, операция, выход или формат дают `ValueError`. Тест `tests/test_source_transport.py` проверяет, что каждый ID из поставляемого файла есть в `manga_native_registry.profiles()` и что домен `ROOT` адаптера покрыт его правилами.

## Как запрос узнаёт источник и операцию

Адаптеру ничего делать не нужно. Диспетчеры открывают область источника:

- `manga_native_sources.search` открывает `search`;
- `manga_native_sources.catalogue_job` открывает `catalogue`, для дозагрузки карточки — `details`;
- `manga_sources.inspect` для нативного адаптера открывает `chapters` для карточки тайтла и `pages` для ссылки на главу. Различает их `adapter.is_chapter` или `CHAPTER_PATH`;
- картинки страниц приходят через прокси читалки без области. Источник определяется по `Referer` главы через `manga_native_sources.for_url`, операция — `images`. Поиск по `Referer` выполняется только для доменов, которые есть в декларациях.

Если адаптер вызывается вне этих путей, например в скрипте, область задают явно:

```python
http = PublicHttp(timeout=(3, 12), source=adapter.SOURCE_ID, operation='catalogue')
with http.scope(adapter.SOURCE_ID, 'chapters'):
    detail = adapter.inspect(url, http)
```

`PublicHttp`, созданный внутри области, наследует её через `contextvars`. `http.fork()` копирует источник и операцию. В потоках `ThreadPoolExecutor` контекст не наследуется, поэтому туда передают сам `http` или `http.fork()`.

## Браузерная проверка и Byparr

Проверкой считается ответ Cloudflare или DDoS-Guard: заголовок `cf-mitigated: challenge`, страница «Just a moment», `/cdn-cgi/challenge-platform`, `cf-chl-`. Блокировки WAF («Access denied»), бан страны, вход и подписка проверкой не считаются, решатель для них не вызывается.

Если правило запроса разрешает `solver`:

1. Транспорт вызывает Byparr (`POST /v1`, `request.get`) для исходного URL. Для POST вызывает его для корня сайта.
2. Byparr возвращает гостевые куки и свой `User-Agent`. Остаются только куки этого домена. Ответ для другого сайта отклоняется.
3. Исходный запрос повторяется с этими куками и этим `User-Agent` через тот же выход.
4. Сессия привязана к ключу `(источник, домен, выход)` и живёт 25 минут. Следующие запросы сразу идут с ней.
5. Параллельные запросы одного ключа ждут один запуск решателя (single-flight). Одновременно работают не больше двух решателей. Неудача запоминается на 90 секунд, чтобы не нагружать Byparr повторами.
6. Если сайт не принимает решённые куки вне браузера (отпечаток TLS), а адаптер ждёт страницу, транспорт отдаёт HTML, отрисованный самим Byparr. Страницей считается вызов `http.document()` методом GET без `Accept` для JSON, protobuf, RSC или картинок, и правило с `format` `html` или `any`. JSON, картинки и CBZ HTML не получают никогда, для них такой исход — `SourceChallengeError(solver='rejected')`.

Для правила `exit: "japan"` Byparr получает японский прокси в заголовке `X-Proxy-Server`, поэтому решатель и повторный запрос выходят через один IP. Перед запуском решателя транспорт перечитывает идентификатор выхода. Если выход сменился, запрос завершается `SourceRouteError`, а сессии старого выхода удаляются.

Сессии хранятся в памяти процесса импортёра и не пишутся на диск. После перезапуска первый запрос снова вызывает решатель.

Бюджет: решатель получает оставшееся время запроса минус 10 секунд на повторный запрос, но не больше `solver.maxTimeout`. Byparr ждёт затишья сети до конца этого времени, поэтому без запаса повтор не успевает. Если на решатель остаётся меньше 6 секунд, он не запускается (`solver='budget'`). Для источников с решателем диспетчеры расширяют дедлайн поиска и каталога до `solverBudget` через `source_transport.solver_budget(source_id, normal)`.

## Статусы ошибок

Все классы — подклассы прежних, поэтому существующие обработчики (`except SourceAccessError`, `except SourceTemporaryError`, переход на Suwayomi в `catalogue_sources`) работают как раньше. Машинный статус возвращает `source_parser.source_status(error)`.

| Статус | Класс | Когда |
| --- | --- | --- |
| `challenge` | `SourceChallengeError(SourceAccessError)` | Проверка не пройдена. Поле `solver`: `none` (решатель не объявлен), `unavailable`, `failed`, `busy`, `budget`, `cooldown`, `rejected`. |
| `rate_limited` | `SourceRateLimitError` | HTTP 429, `retry_after` в секундах. |
| `region_blocked` | `SourceRegionError(SourceAccessError)` | HTTP 451, Cloudflare 1009, страница о недоступности в регионе. На ответах 2xx текст о регионе не проверяется. |
| `paid_chapter` | `SourcePaidError(SourceAccessError)` | В ответе `requires_subscription`, `subscription_required`, `requires_purchase` или `is_paid_locked`. |
| `auth_required` | `SourceAuthError(SourceAccessError)` | HTTP 401 или `requires_authentication` / `login_required`. |
| `parser_error` | `SourceParserError(SourceError)` | Ответ пришёл, но в непонятном формате. Старые `SourceError` с текстом «изменил формат» и `ValueError`/`KeyError` из адаптера `source_status` тоже относит сюда. |
| `route_unavailable` | `SourceRouteError(SourceTemporaryError)` | Японский шлюз не готов, `/status` недоступен, прокси отказал в CONNECT, выход сменился посреди запроса. Это явная временная ошибка, а не «источник не ответил». |
| `access_denied`, `temporary`, `redirect`, `error` | прежние классы | Остальные ответы, как раньше. |

Новые адаптеры для своих проверок формата бросают `SourceParserError`, для платных глав — `SourcePaidError`, для входа — `SourceAuthError`.

## Инфраструктура: контракт со шлюзом и Byparr

Импортёр читает `/data/source-transport.json`. Его пишет установщик сетевых сервисов (`deploy/oracle/install-network-services.py`, агент A):

```json
{
  "version": 1,
  "japan": {"httpProxy": "http://jp-router:8080", "status": "http://jp-vpn:8090/status", "hosts": ["comic-ryu.jp", "..."]},
  "solver": {"url": "http://byparr:8191/v1", "maxTimeout": 60}
}
```

- `httpProxy` — HTTP CONNECT в японский туннель. Если туннель лежит, шлюз должен отказать, а не выпустить запрос через Oracle.
- `status` — JSON `{"ready", "country", "exit", "generation", "fresh", ...}`. Транспорт кэширует его на 10 секунд. Маршрут считается рабочим при `ready: true`, `fresh` не `false` и `country: "JP"`. Идентификатор выхода — `<generation>-<exit>`: после переподключения сессии решателя сбрасываются, даже если IP совпал. Недоступный `/status` означает `route_unavailable` (fail closed).
- `hosts` — белый список роутера. Японский маршрут к домену вне списка отклоняется с явной ошибкой: текущий роутер GOST выпускает такие домены через Oracle молча. `null` означает, что роутер отправляет в Японию любой CONNECT.
- `solver.url` — FlareSolverr-совместимый `POST /v1` Byparr. Японский прокси передаётся заголовком `X-Proxy-Server`. Можно указать отдельный `japanUrl`, тогда для японских правил используется он без заголовка.
- Все адреса — только `http://имя-сервиса[:порт][/путь]` в частной сети Docker.

Пока файла нет, используется старый манифест `/data/manga-source-routes.json`: прокси `suwayomi-jp-router:8080`, его белый список, Byparr на `http://byparr:8191/v1`, идентификатор выхода `japan:legacy`. Тогда сессии сбрасываются только при отказе прокси.

`source_transport.describe()` возвращает режим, наличие прокси и статуса, адрес решателя и список сессий без кук.

## Проверка

- `tests/test_source_transport.py` — контрактные тесты. Сайты, `/status` шлюза и Byparr в них замоканы, сети нет.
- `scripts/check-source-transport.py --host mediavault-vm <ID>...` — живая проверка на импортёре. Скрипт отправляет `server/` текущей ветки архивом в контейнер и для каждого ID проходит каталог, точный поиск, карточку, главу и первую картинку в области источника. Он ничего не включает и не переключает с Suwayomi, состояние индекса и здоровья не пишет. При активном `/opt/mediavault/deploy.lock` не запускается.
- `scripts/probe-native-source-batch.py` тоже работает в области источника. Для источников с решателем дедлайны увеличены на `solverBudget`.

## Порядок для переносимого расширения

1. Написать адаптер как обычно, на `http.document()` / `http._open()`. Прокси, куки решателя и `User-Agent` вручную не выставлять.
2. Если источнику нужна Япония или он за Cloudflare, добавить запись в `manga_source_transport.json`: ID, домены каталога и CDN, операции, выход, `solver`, `format`.
3. Японский домен должен быть и в белом списке шлюза (`japan.hosts`, либо `manga-source-routes.json` до перехода). Иначе запрос завершится явной ошибкой, а не уйдёт через Oracle.
4. Прогнать `tests/test_source_transport.py` (проверка ID и домена `ROOT`) и `scripts/check-source-transport.py` для нового ID.
5. Включение профиля и отключение от Suwayomi делают агенты C и E по своим правилам. Транспорт их не меняет.
