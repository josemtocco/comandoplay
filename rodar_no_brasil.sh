#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "[ERRO] Python 3 não encontrado." >&2; exit 1; fi

"$PY" -c "import aiohttp" 2>/dev/null || {
  echo "Instalando aiohttp..."
  "$PY" -m pip install -q aiohttp || pip3 install -q aiohttp
}

echo "============================================================"
echo " ComandoPlay M3U — otimizado para SS IPTV (MP4 primeiro)"
echo "============================================================"

EXTRA=()
PUSH=0
HAS_PREFER=0
for arg in "$@"; do
  if [ "$arg" = "--push" ]; then PUSH=1
  else
    EXTRA+=("$arg")
    [ "$arg" = "--prefer" ] && HAS_PREFER=1
  fi
done
if [ "$HAS_PREFER" = "0" ]; then EXTRA=(--prefer mp4 "${EXTRA[@]}"); fi

"$PY" gerar_comandoplay.py "${EXTRA[@]}"

echo
echo "Pronto! → playlists/comandoplay.m3u"
echo "Use no SS IPTV em seguida (MP4 assinado expira)."

if [ "$PUSH" = "1" ]; then
  command -v git >/dev/null 2>&1 || { echo "[ERRO] git não encontrado"; exit 1; }
  mkdir -p playlists
  git add playlists/comandoplay.m3u
  if git diff --staged --quiet; then echo "Nenhuma mudança."
  else
    git commit -m "Atualização lista VOD ComandoPlay (SS IPTV)"
    git pull --rebase --autostash origin main || true
    git push origin HEAD:main
    echo "Enviado."
  fi
fi
