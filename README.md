# runtime-vod-m3u

Gerador de playlist M3U para SS IPTV a partir do catálogo VOD público da Runtime.

## O que faz

- Descobre páginas de conteúdo em português no catálogo Runtime.
- Extrai título, gêneros, descrição, imagem e URL da página.
- Abre as páginas com Chromium/Playwright e captura URLs públicas de reprodução HLS (`.m3u8`) e DASH (`.mpd`) observadas na rede.
- Ignora DRM/EME e não tenta contornar autenticação ou proteções.
- Testa os manifestos encontrados antes de colocá-los na playlist.
- Mantém um catálogo incremental em `catalogo.json`.
- Mantém somente itens que continuam ativos; novos itens são acrescentados.
- Gera `runtime_vod.m3u`, otimizada para SS IPTV, com o título real do conteúdo.
- Executa automaticamente a cada 6 horas pelo GitHub Actions.

## Arquivos

- `gerar_m3u.py`: entrada principal.
- `runtime_scraper.py`: descoberta do catálogo, páginas e streams.
- `catalogo.json`: estado incremental; é atualizado pelo workflow.
- `runtime_vod.m3u`: playlist final.
- `requirements.txt`: dependências Python.
- `.github/workflows/atualizar.yml`: atualização automática.

## Execução local

```bash
pip install -r requirements.txt
python -m playwright install chromium
python gerar_m3u.py --verbose
```

Para uma varredura rápida durante testes:

```bash
python gerar_m3u.py --max-pages 50 --max-items 20 --verbose
```

## GitHub

1. Crie um repositório chamado `runtime-vod-m3u`.
2. Envie todos os arquivos para a raiz do repositório.
3. Execute manualmente `Actions > Atualizar Runtime VOD > Run workflow` na primeira vez.
4. Depois disso o workflow roda a cada 6 horas.

A playlist publicada no repositório será:

`https://raw.githubusercontent.com/SEU_USUARIO/runtime-vod-m3u/main/runtime_vod.m3u`

Use essa URL no SS IPTV.

## Observações

A Runtime pode alterar seu player, CDN, catálogo e mecanismos de reprodução. O projeto evita depender de links HLS antigos: em cada execução ele tenta descobrir novamente os manifests observados pelo navegador.

Links com DRM/EME não são incluídos. Se uma página não expuser um manifesto público reproduzível, ela permanece no catálogo como não reproduzível e não é adicionada à M3U.
