@echo off
chcp 65001 >nul
REM ============================================================
REM  Gera a lista VOD do Runtime.tv a partir do SEU PC (Brasil)
REM  Rode este arquivo com um duplo-clique.
REM  Precisa ter o Python instalado (https://www.python.org/downloads/).
REM  Importante: rode com seu IP brasileiro, SEM VPN.
REM ============================================================

cd /d "%~dp0"

REM --- localizar o Python (tenta 'py' e depois 'python') ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERRO] Python nao encontrado.
  echo Instale em https://www.python.org/downloads/ e marque "Add Python to PATH".
  pause
  exit /b 1
)

echo ============================================================
echo  Gerando a lista VOD do Runtime.tv (catalogo do Brasil)...
echo  Isso pode levar alguns minutos. Aguarde.
echo ============================================================
%PY% gerar_runtime_vod.py
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao gerar a lista. Veja as mensagens acima.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Pronto! Lista gerada em:
echo    playlists\runtime_vod.m3u
echo ============================================================
echo.

set /p PUB="Deseja enviar a lista para o GitHub agora? (S/N): "
if /i "%PUB%"=="S" (
  where git >nul 2>nul || (echo [ERRO] Git nao encontrado. Instale em https://git-scm.com/download/win & pause & exit /b 1)
  git add playlists/runtime_vod.m3u
  git commit -m "Atualizacao manual da lista VOD (gerada no Brasil)"
  git pull --rebase --autostash origin main
  git push origin HEAD:main
  echo.
  echo Enviado para o GitHub.
)

echo.
pause
