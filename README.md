# runtime-vod-m3u v4

Projeto para gerar uma M3U de VOD da **Runtime Brasil**, otimizada para SS IPTV.

## Objetivo

A versão 4 é específica para o catálogo brasileiro. Ela força URLs `/pt-br/...`, percorre as categorias/coleções brasileiras e só inclui um título quando consegue capturar uma reprodução pública cuja variante HLS indique áudio em português (`pt`, `pt-BR` ou `por`).

A versão anterior podia abrir `/feature/...` internacional e capturar manifests cujo `defaultAudioLang` era `en`. Essa versão evita esse comportamento.

## Fluxo

1. Abre `https://www.runtime.tv/pt-br`.
2. Descobre coleções/categorias e normaliza tudo para `/pt-br/collections/...`.
3. Percorre cada categoria com rolagem/carregamento progressivo.
4. Normaliza cada filme para `/pt-br/feature/...`.
5. Abre cada título no Chromium em locale `pt-BR`.
6. Tenta selecionar áudio Português/Portuguese quando o player expõe essa opção.
7. Captura `.m3u8`/`.mpd` do player.
8. Para HLS, verifica o manifesto e o payload para identificar áudio português.
9. Descarta conteúdos cujo stream identificado seja explicitamente inglês.
10. Gera `runtime_vod.m3u` com o nome real do conteúdo.
11. Opcionalmente encurta a URL final com TinyURL.
12. Mantém o catálogo incremental e preserva a M3U anterior se a descoberta falhar completamente.

## Atualização

O GitHub Actions executa a atualização a cada 6 horas e também pode ser iniciado manualmente.

## Importante

O fato de a página estar em `/pt-br` não garante, por si só, que a faixa de áudio do vídeo seja dublada em português. Por isso a v4 exige uma indicação de idioma no stream/player quando disponível.

Não há tentativa de contornar DRM, autenticação ou proteção de conteúdo. Apenas streams públicos disponibilizados pela própria página são considerados.
