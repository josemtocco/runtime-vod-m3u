# runtime-vod-m3u v3

Projeto para gerar uma playlist M3U de conteúdos VOD públicos disponibilizados pela Runtime, otimizada para SS IPTV.

## O que mudou na v3
- Descobre categorias no menu/DOM renderizado.
- Visita cada categoria encontrada.
- Rola a página e tenta carregar mais conteúdos até estabilizar.
- Usa uma lista de slugs de gêneros como fallback para categorias que não aparecem no HTML inicial.
- Abre cada página de filme individualmente.
- Captura manifests HLS `.m3u8` e DASH `.mpd` expostos pelo player público.
- Mantém o título real do filme.
- Gera grupos `Runtime | gênero`.
- Atualiza a cada 6 horas.
- Encurta URLs com TinyURL por padrão (`SHORTEN_URLS=true`). A URL original permanece em `catalogo.json` para permitir renovação na próxima execução.
- Se uma execução não processar nenhum VOD, preserva a M3U anterior.

## GitHub Actions
Execute manualmente em Actions → Atualizar Runtime VOD → Run workflow. Depois o workflow roda a cada 6 horas.

## Observação sobre TinyURL
TinyURL apenas redireciona para a URL original. Isso não transforma um manifesto temporário em permanente. Se a URL de origem tiver token de expiração, o workflow precisa capturar uma nova URL a cada execução. O projeto faz isso.

O projeto utiliza somente URLs públicas que o próprio site disponibiliza ao navegador e não tenta contornar DRM, login ou controles de acesso.
