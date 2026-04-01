# Deduplicate all Chroma collections by fingerprint.
# Copies the dedup script into the app container, lists collections, then runs dedup per collection.

CTN="${CTN:-chat_ui_app}"
CHROMA_HOST="${CHROMA_HOST:-127.0.0.1}"
CHROMA_PORT="${CHROMA_PORT:-8001}"

podman cp utilities/dedup_chroma.py "${CTN}":/app

collections=$(podman exec -i "${CTN}" bash -lc "
python - <<'PY'
from chromadb import HttpClient
from chromadb.config import Settings
cli = HttpClient(host='${CHROMA_HOST}', port=${CHROMA_PORT}, settings=Settings(anonymized_telemetry=False, allow_reset=True))
names = [c.name for c in cli.list_collections()]
print(' '.join(names))
print(f'Total collections: {len(names)}')
PY
")

echo "${collections}"

# Extract first line of names (space-separated)
name_line=$(echo "${collections}" | head -n1 | tr -d '\r')
for coll in ${name_line}; do
  echo "Deduping collection: ${coll}"
  podman exec -i "${CTN}" bash -lc "CHROMA_COLLECTION='${coll}' python /app/dedup_chroma.py"
done
