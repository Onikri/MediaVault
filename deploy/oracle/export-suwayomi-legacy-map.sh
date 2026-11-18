#!/bin/bash
# Export Suwayomi's numeric title/chapter IDs into MediaVault's own legacy ID map.
#
#   sudo bash export-suwayomi-legacy-map.sh <path to server/suwayomi_legacy.py>
#
# Read-only against Suwayomi: it copies the H2 database file and reads the copy
# with Suwayomi's own jar in a network-less container (the running JVM is not
# queried for titles or chapters); only the source list (base URLs) is read
# once through the importer's authenticated bridge. The map is merged into
# /data/suwayomi-legacy-map.sqlite (rows are only added or refreshed) and a
# copy is kept in /srv/mediavault/backups/suwayomi-legacy-map-<time>/.
set -euo pipefail
MODULE=${1:?path to suwayomi_legacy.py}
DATA=${MEDIAVAULT_DATA:-/srv/mediavault/importer-data}
BACKUPS=${MEDIAVAULT_BACKUPS:-/srv/mediavault/backups}
H2=${SUWAYOMI_DB:-/opt/mediavault-suwayomi/data/database.mv.db}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK=/srv/mediavault/tmp/suwayomi-legacy-$STAMP
OWNER=$(stat -c %u:%g "$DATA/service.key")
SUWAYOMI_IMAGE=$(docker inspect oracle-suwayomi-1 --format '{{.Image}}')
IMPORTER_IMAGE=$(docker inspect oracle-importer-1 --format '{{.Config.Image}}')
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
mkdir -p "$WORK"
cp "$MODULE" "$WORK/suwayomi_legacy.py"
cp --reflink=auto "$H2" "$WORK/database.mv.db"
cat > "$WORK/export.sql" <<'SQL'
CALL CSVWRITE('/w/manga.csv', 'SELECT ID, SOURCE, URL, REAL_URL, TITLE, THUMBNAIL_URL, IN_LIBRARY, INITIALIZED FROM MANGA ORDER BY ID', 'charset=UTF-8');
CALL CSVWRITE('/w/chapter.csv', 'SELECT MANGA, SOURCE_ORDER, ID, URL, REAL_URL, NAME, CHAPTER_NUMBER, SCANLATOR, PAGE_COUNT FROM CHAPTER ORDER BY MANGA, SOURCE_ORDER', 'charset=UTF-8');
CALL CSVWRITE('/w/source.csv', 'SELECT S.ID, S.NAME, S.LANG, E.PKG_NAME, E.NAME EXT_NAME, E.IS_INSTALLED, E.VERSION_NAME FROM SOURCE S LEFT JOIN EXTENSION E ON E.ID=S.EXTENSION ORDER BY S.ID', 'charset=UTF-8');
SQL
docker run --rm --network none --user 0 -v "$WORK":/w --entrypoint java "$SUWAYOMI_IMAGE" \
  -cp /home/suwayomi/startup/tachidesk_latest.jar org.h2.tools.RunScript \
  -url 'jdbc:h2:/w/database;ACCESS_MODE_DATA=r' -user '' -password '' -script /w/export.sql >/dev/null
rm -f "$WORK/database.mv.db"
# Base URLs live only in the running extensions; one read of /source/list.
docker exec -i -w /app oracle-importer-1 python - > "$WORK/sources.json" <<'PY'
import json
from suwayomi_bridge import Client
client = Client()
try:
    rows = client.get('/source/list', timeout=40)
finally:
    client.close()
print(json.dumps([{'id': str(s['id']), 'name': s.get('name'), 'lang': s.get('lang'), 'baseUrl': s.get('baseUrl'),
                   'isNsfw': bool(s.get('isNsfw'))} for s in rows], ensure_ascii=False))
PY
if [ -f "$DATA/suwayomi-legacy-map.sqlite" ]; then cp "$DATA/suwayomi-legacy-map.sqlite" "$WORK/map.sqlite"; fi
docker run --rm --network none --user 0 -e PYTHONPATH=/app -v "$WORK":/w -w /w --entrypoint python "$IMPORTER_IMAGE" \
  /w/suwayomi_legacy.py build --export /w --sources /w/sources.json --map /w/map.sqlite | tee "$WORK/build.json"
python3 - "$WORK/map.sqlite" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert db.execute('SELECT count(*) FROM manga').fetchone()[0] > 0
PY
mkdir -p "$BACKUPS/suwayomi-legacy-map-$STAMP"
cp "$WORK/map.sqlite" "$BACKUPS/suwayomi-legacy-map-$STAMP/suwayomi-legacy-map.sqlite"
cp "$WORK/build.json" "$WORK/sources.json" "$BACKUPS/suwayomi-legacy-map-$STAMP/"
(cd "$BACKUPS/suwayomi-legacy-map-$STAMP" && sha256sum suwayomi-legacy-map.sqlite > SHA256SUMS)
chmod 700 "$BACKUPS/suwayomi-legacy-map-$STAMP"; chmod 600 "$BACKUPS/suwayomi-legacy-map-$STAMP"/*
install -m 600 -o "${OWNER%:*}" -g "${OWNER#*:}" "$WORK/map.sqlite" "$DATA/.suwayomi-legacy-map.sqlite.new"
mv -f "$DATA/.suwayomi-legacy-map.sqlite.new" "$DATA/suwayomi-legacy-map.sqlite"
echo "map: $DATA/suwayomi-legacy-map.sqlite backup: $BACKUPS/suwayomi-legacy-map-$STAMP"
