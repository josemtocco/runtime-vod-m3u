# Runtime VOD — Brasil (busca profunda)

Projeto para gerar uma playlist M3U leve para SS IPTV usando somente conteúdo público do catálogo brasileiro da Runtime (`/pt-br/`).

## O que esta versão corrige

A versão anterior encontrou somente uma fração do catálogo. Esta versão não depende de uma lista fixa de categorias. Ela combina várias camadas de descoberta:

1. página inicial e menu brasileiro;
2. rolagem/infinite scroll e botões de carregar mais;
3. todas as coleções encontradas no site;
4. exploração recursiva da navegação pública;
5. sitemap.xml / sitemap index / robots.txt quando disponíveis;
6. respostas JSON/API/GraphQL públicas observadas pelo navegador;
7. URLs de filmes encontradas dentro de HTML, JavaScript e JSON;
8. categorias conhecidas apenas como complemento, sempre em `/pt-br/`;
9. abertura individual de cada página de filme para descobrir o stream;
10. tentativa de seleção de áudio Português/Português (Brasil);
11. validação do HLS para não aceitar deliberadamente uma faixa identificada como inglês.

A busca profunda é complementar: nenhuma fonte de descoberta substitui as outras.

## Atualização

O GitHub Actions executa automaticamente a cada 6 horas e também permite execução manual.

## Incremental

`catalogo.json` mantém os registros já conhecidos. A cada execução são adicionados novos títulos e atualizados os encontrados novamente. A M3U contém somente itens ativos com stream válido. Se uma execução não encontrar nenhum item, o projeto preserva a M3U anterior para evitar apagar a playlist por uma falha temporária.

## SS IPTV

A playlist usa `#EXTINF`, `tvg-name`, `tvg-logo` e `group-title`. Os links podem ser encurtados com TinyURL (`SHORTEN_URLS=true`). O encurtamento é somente um redirecionamento: não transforma um stream temporário em permanente.

## Limites

A execução padrão permite até 300 coleções e 10.000 páginas VOD descobertas. O objetivo é alcançar o catálogo completo disponível publicamente, sem depender de uma contagem artificial de filmes.

## Importante

O projeto acessa somente páginas e streams públicos disponibilizados pelo site. Não tenta contornar DRM, autenticação, assinatura ou outros controles de acesso.
