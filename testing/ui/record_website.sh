#!/usr/bin/env bash
# Record a video walkthrough of the NGU storefront.
#
# Boots the seeded e2e backend (:8000), the Vite dev server (:5173, proxies
# /api -> :8000), drives the real React storefront with Playwright, and
# transcodes the capture to testing/reports/ngu_storefront_walkthrough.mp4.
#
# Prereqs: backend venv, frontend node_modules, and `npm i -D playwright &&
# npx playwright install chromium chromium-headless-shell` (run once in this dir).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTING="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$TESTING/.." && pwd)"
BACKEND="$REPO/Backend"
PY="$BACKEND/venv/Scripts/python.exe"
FRONTEND="$REPO/Frontend/nidhi-brand-forge"
export USE_CLOUDINARY=False USE_S3=False SECRET_KEY=e2e-insecure
SETTINGS=spices_backend.e2e_settings

cleanup() {
  [[ -n "${BACK_PID:-}" ]] && kill "$BACK_PID" 2>/dev/null
  [[ -n "${VITE_PID:-}" ]] && kill "$VITE_PID" 2>/dev/null
}
trap cleanup EXIT

echo "==> migrate + seed e2e database"
rm -f "$BACKEND/e2e_db.sqlite3"
( cd "$BACKEND" && "$PY" manage.py migrate --noinput --settings=$SETTINGS >/dev/null )
( cd "$BACKEND" && "$PY" "$HERE/../tools/seed_e2e.py" )

echo "==> start backend on :8000"
( cd "$BACKEND" && "$PY" manage.py runserver 127.0.0.1:8000 --noreload --settings=$SETTINGS ) &
BACK_PID=$!
for i in $(seq 1 30); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health/)" == "200" ]] && break
  sleep 1
done

echo "==> start vite dev server on :5173"
( cd "$FRONTEND" && npm run dev ) &
VITE_PID=$!
for i in $(seq 1 40); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/)" == "200" ]] && break
  sleep 1
done

echo "==> record walkthrough"
( cd "$HERE" && node record_walkthrough.cjs http://127.0.0.1:5173 videos )

echo "==> transcode to mp4"
WEBM="$(ls -t "$HERE"/videos/*.webm | head -1)"
FFMPEG="$("$PY" -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')"
"$FFMPEG" -y -i "$WEBM" -movflags +faststart -pix_fmt yuv420p \
  "$TESTING/reports/ngu_storefront_walkthrough.mp4"
echo "==> done: testing/reports/ngu_storefront_walkthrough.mp4"
