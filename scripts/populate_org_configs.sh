#!/bin/bash
# Populate documents/repo/splunk/ with organization-specific .conf files.
#
# Usage:
#   bash scripts/populate_org_configs.sh /path/to/splunk/etc/apps
#   bash scripts/populate_org_configs.sh /opt/splunk/etc/apps
#
# This copies macros.conf, savedsearches.conf, and commands.conf from the
# Splunk installation into the directory the pipeline loads at startup.

set -euo pipefail

SRC="${1:?Usage: $0 /path/to/splunk/etc/apps}"
DEST="documents/repo/splunk"

if [ ! -d "$SRC" ]; then
    echo "ERROR: Source directory does not exist: $SRC"
    exit 1
fi

mkdir -p "$DEST"

echo "Copying org configs from $SRC to $DEST ..."

TOTAL=0
for CONF in macros.conf savedsearches.conf commands.conf indexes.conf props.conf transforms.conf datamodels.conf; do
    COUNT=$(find "$SRC" -name "$CONF" -not -path "*/README/*" 2>/dev/null | wc -l)
    if [ "$COUNT" -gt 0 ]; then
        # Merge all found files into one (append), preserving stanza headers
        find "$SRC" -name "$CONF" -not -path "*/README/*" -exec cat {} + > "$DEST/$CONF"
        echo "  $CONF: merged $COUNT file(s)"
        TOTAL=$((TOTAL + COUNT))
    fi
done

echo "Done. Copied $TOTAL config file(s) to $DEST/"
echo "Restart the app to load the new configurations."
