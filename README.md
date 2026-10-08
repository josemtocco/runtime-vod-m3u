# Runtime VOD Brasil — v6

Projeto para gerar uma M3U leve para SS IPTV usando somente conteúdo público do catálogo brasileiro da Runtime.

## O que foi corrigido

- Descoberta profunda do catálogo `/pt-br`.
- Descoberta por página inicial, coleções, sitemap/robots e respostas públicas JSON/API.
- Paginação real e links de próxima página, além de infinite scroll/load more.
- As categorias são complemento; não são o único mecanismo de descoberta.
- URLs de filmes são normalizadas para `/pt-br/feature/...`.
- O scraper não exige que todo manifesto HLS declare `LANGUAGE=pt`; se não houver indicação explícita de inglês, o stream obtido do player brasileiro pode ser aceito.
- Streams explicitamente identificados como inglês são rejeitados.
- Processamento usa um pequeno pool de páginas, em vez de criar um navegador/contexto novo para cada filme.
- Limites de 1.200 filmes e 30 minutos no GitHub Actions para evitar execuções intermináveis.
- Proteção contra M3U vazia ou queda anormal: uma execução que encontre zero streams, ou muito menos que a anterior, preserva a M3U válida existente.
- TinyURL é reutilizado quando o stream não mudou.
- Atualização automática a cada 6 horas.

## Execução local

```bash
pip install -r requirements.txt
python -m playwright install chromium
python gerar_m3u.py --max-categories 120 --max-items 1200 --concurrency 6 --verbose
```

## GitHub Actions

O workflow `Atualizar Runtime VOD Brasil` roda a cada 6 horas e também pode ser iniciado manualmente.

A M3U só é substituída quando existe uma quantidade válida de streams. Uma falha do site/player não deve apagar uma lista anterior que esteja funcionando.

## Observação sobre áudio

A página brasileira do Runtime confirma que os títulos existem no catálogo `/pt-br`. A versão também verifica informações de áudio expostas pelo player/manifesto quando disponíveis. Não é feita tentativa de contornar DRM, login ou qualquer controle de acesso.
