#!/bin/sh
set -e

PUBLISHER="${ISAP_PUBLISHER:-DU}"
MONGODB_URI="${MONGODB_URI:-mongodb://mongodb:27017/}"
DB="${ISAP_MONGO_DB:-legal_acts}"
COLLECTION="${ISAP_MONGO_COLLECTION:-isap}"
CHANGES_COLLECTION="${ISAP_CHANGES_COLLECTION:-changes}"
HTML_DIR="${ISAP_HTML_DIR:-/isap_data}"
SLEEP="${ISAP_SLEEP:-0.15}"

YEAR_FROM="${ISAP_YEAR_FROM:-${ISAP_YEAR:-2015}}"
YEAR_TO="${ISAP_YEAR_TO:-${ISAP_YEAR:-2018}}"

year="${YEAR_FROM}"
while [ "${year}" -le "${YEAR_TO}" ]; do
    echo "[crawler] Starting crawl: publisher=${PUBLISHER} year=${year}"
    python isap_crawler.py \
        --year "${year}" \
        --publisher "${PUBLISHER}" \
        --mongodb-uri "${MONGODB_URI}" \
        --db "${DB}" \
        --collection "${COLLECTION}" \
        --html-dir "${HTML_DIR}" \
        --sleep "${SLEEP}" \
        ${SKIP_HTML:+--skip-html} \
        ${SKIP_PDF:+--skip-pdf}
    echo "[crawler] Crawl done for year=${year}. Starting change extraction..."
    python isap_extract_changes.py \
        --mongodb-uri "${MONGODB_URI}" \
        --db "${DB}" \
        --isap-collection "${COLLECTION}" \
        --changes-collection "${CHANGES_COLLECTION}" \
        --assets-dir "${HTML_DIR}" \
        --year "${year}"
    year=$((year + 1))
done

echo "[crawler] All done."
