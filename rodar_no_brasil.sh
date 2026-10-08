#!/usr/bin/env bash
# ============================================================
#  Gera a lista VOD do Runtime.tv a partir do SEU computador
#  (Linux / macOS). Rode com seu IP brasileiro, SEM VPN.
#
#  Uso:
#    chmod +x rodar_no_brasil.sh   # (so na primeira vez)
#    ./rodar_no_brasil.sh          # gera a lista
#    ./rodar_no_brasil.sh --push   # gera e envia pro GitHub
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

# --- localizar o Python 3 ---
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[ERRO] Python 3 nao encontrado. Instale o Python 3 e tente de novo." >&2
  exit 1
fi

echo "============================================================"
echo " Gerando a lista VOD do Runtime.tv (catalogo do Brasil)..."
echo " Isso pode levar alguns minutos. Aguarde."
echo "============================================================"
"$PY" gerar_runtime_vod.py

echo
echo "============================================================"
echo " Pronto! Lista gerada em: playlists/runtime_vod.m3u"
echo "============================================================"

# --- envio opcional para o GitHub ---
if [ "${1:-}" = "--push" ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[ERRO] Git nao encontrado. Instale o git para usar --push." >&2
    exit 1
  fi
  git add playlists/runtime_vod.m3u
  if git diff --staged --quiet; then
    echo "Nenhuma mudanca na lista; nada para enviar."
  else
    git commit -m "Atualizacao manual da lista VOD (gerada no Brasil)"
    git pull --rebase --autostash origin main || true
    git push origin HEAD:main
    echo "Enviado para o GitHub."
  fi
fi
