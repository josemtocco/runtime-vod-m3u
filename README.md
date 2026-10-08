# runtime-vod-m3u

Projeto para gerar uma playlist M3U de conteúdos VOD públicos disponibilizados pela Runtime, para uso no SS IPTV.

## O que esta versão faz

- Descobre páginas VOD por sitemap/robots.txt.
- Descobre páginas adicionais pelo HTML e pelo DOM renderizado com Chromium.
- Percorre coleções da Runtime.
- Abre cada página VOD com Playwright.
- Captura manifests HLS `.m3u8` ou DASH `.mpd` observando a rede e recursos do player.
- Extrai o título real do conteúdo, gênero e imagem.
- Gera `runtime_vod.m3u` otimizada para SS IPTV.
- Atualiza automaticamente a cada 6 horas.
- Mantém itens antigos somente quando o manifesto anterior ainda responde como playlist válida.
- Se a Runtime bloquear/alterar a descoberta e nenhum conteúdo for encontrado, a playlist anterior não é apagada.
- Usa `ubuntu-24.04` para evitar o aviso de migração do `ubuntu-latest`.

## Instalação

Envie todos os arquivos para a raiz do repositório GitHub, mantendo `.github/workflows/atualizar.yml`.

Depois execute manualmente:

```bash
python gerar_m3u.py --max-pages 250 --max-items 600 --concurrency 3 --verbose
```

O resultado será `runtime_vod.m3u`.

## Atualização

O GitHub Actions executa a cada 6 horas e também possui `workflow_dispatch` para execução manual.

## Observação

A playlist utiliza somente URLs de reprodução públicas que o player/site disponibilizar ao navegador. Não há tentativa de contornar DRM, autenticação ou proteção de conteúdo.
