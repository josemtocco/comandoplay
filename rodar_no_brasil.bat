@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  ComandoPlay M3U — otimizado para SS IPTV (MP4 primeiro)
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    pause
    exit /b 1
  )
  set PY=py
) else (
  set PY=python
)

%PY% -c "import aiohttp" 2>nul
if errorlevel 1 (
  echo Instalando aiohttp...
  %PY% -m pip install -q aiohttp
)

%PY% gerar_comandoplay.py --prefer mp4 %*
if errorlevel 1 (
  echo [ERRO] Falha na geracao.
  pause
  exit /b 1
)

echo.
echo Pronto! playlists\comandoplay.m3u
echo Abra no SS IPTV em seguida (links MP4 expiram com o tempo).
echo.
pause
