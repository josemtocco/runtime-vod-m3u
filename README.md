# Lista M3U VOD do Runtime.tv (atualizacao automatica)

Este projeto gera uma lista **M3U** com todo o **conteudo sob demanda (VOD)** do
[Runtime.tv](https://www.runtime.tv/) — Filmes e Series — com o **nome de cada
conteudo**, pronta para usar no **SS IPTV**, **VLC** e players compativeis.

O GitHub Actions regenera a lista **a cada 6 horas**, automaticamente.

## Filtro de idioma (apenas portugues)

A lista esta configurada para incluir **somente conteudo em portugues**
(`pt` / `pt-br`). Isso e controlado pela variavel `ONLY_PORTUGUESE = True` no
inicio do arquivo `gerar_runtime_vod.py`. Para voltar a incluir todo o catalogo
(todos os idiomas), basta trocar para `ONLY_PORTUGUESE = False`.

> **Importante sobre regiao:** o catalogo do Runtime.tv depende do IP de quem
> coleta. Rodando fora do Brasil (como no GitHub Actions, cujos servidores
> ficam nos EUA) aparecem **poucos titulos em portugues** (cerca de 20 filmes).
> Rodando o script `gerar_runtime_vod.py` em uma **maquina/IP brasileiro**, o
> catalogo em portugues fica **completo** (muito mais filmes e novelas/series
> dubladas ou legendadas em PT-BR). Para a lista mais rica em portugues,
> gere a partir do Brasil e publique o resultado.

## O que a lista contem

- Cada item traz o nome do conteudo (`tvg-name` e titulo) e a capa (`tvg-logo`).
- Agrupamento por `group-title`, **separado por genero**:
  - `Filmes \u2022 <Genero>` — ex.: `Filmes \u2022 Drama`, `Filmes \u2022 Acao`,
    `Filmes \u2022 Terror`, `Filmes \u2022 Comedia`...
  - `Series \u2022 <Genero> \u2022 <Nome da serie>` — cada serie/novela fica
    agrupada dentro do seu genero, com cada episodio nomeado.
  - Os nomes de genero sao normalizados para portugues (Drama, Acao, Comedia,
    Documentario, Suspense, Ficcao Cientifica, Terror, Romance, Familia,
    Crime, Aventura, Animacao, Reality, Historia, etc.).
- Os links de video sao HLS diretos (Kaltura), que o proprio player abre.

## Correcao: "so audio, sem imagem"

O master HLS original do Runtime.tv (Kaltura) incluia uma variante **somente de
audio** (sem resolucao, menor bitrate) junto das variantes de video. Players
simples como o **SS IPTV** acabavam escolhendo essa variante e reproduziam
**so o audio, sem imagem**. A lista agora monta a URL apontando **apenas para
as variantes de video** (que ja vem muxadas: video H.264 + audio AAC no mesmo
fluxo), eliminando a trilha so-audio. Resultado: imagem + som normais no VLC e
no SS IPTV. Como a URL continua sendo um `playManifest` do Kaltura (sem
assinatura embutida), ela permanece valida e os segmentos sao renovados a cada
reproducao.

## Como publicar no GitHub

1. Crie um repositorio novo (pode ser publico) no GitHub.
2. Envie todos os arquivos desta pasta para o repositorio, mantendo a estrutura:
   ```
   gerar_runtime_vod.py
   playlists/runtime_vod.m3u
   .github/workflows/update.yml
   README.md
   ```
3. No GitHub, abra **Settings > Actions > General > Workflow permissions** e
   marque **Read and write permissions** (para o robo poder atualizar a lista).
4. Pronto. O workflow roda sozinho a cada 6 horas. Para rodar na hora, va em
   **Actions > Atualizar lista VOD Runtime.tv > Run workflow**.

## URL para usar no SS IPTV

Depois de enviar ao GitHub, use o link **raw** da lista (troque `USUARIO` e
`REPOSITORIO` pelos seus):

```
https://raw.githubusercontent.com/USUARIO/REPOSITORIO/main/playlists/runtime_vod.m3u
```

No **SS IPTV**: Configuracoes > Listas de reproducao > Adicionar > cole a URL
externa acima > Salvar.

## Rodar manualmente no PC (opcional)

```bash
python gerar_runtime_vod.py
```

Gera/atualiza `playlists/runtime_vod.m3u`.

## Gerar o catalogo COMPLETO no Brasil (recomendado)

Como o catalogo depende do IP de quem coleta, para pegar **todos os filmes e
series em portugues** voce precisa gerar a lista a partir de um **IP
brasileiro** (sua internet de casa, **sem VPN**). Preparei scripts prontos:

- **Windows:** de um duplo-clique em **`rodar_no_brasil.bat`**.
  - Ele roda a geracao e, no fim, pergunta se voce quer enviar a lista pro
    GitHub (digite `S` para enviar).
  - Precisa ter o [Python](https://www.python.org/downloads/) instalado
    (na instalacao, marque **"Add Python to PATH"**).

- **Linux / macOS:** rode no terminal, dentro da pasta do projeto:
  ```bash
  chmod +x rodar_no_brasil.sh    # so na primeira vez
  ./rodar_no_brasil.sh           # gera a lista
  ./rodar_no_brasil.sh --push    # gera e ja envia pro GitHub
  ```

> O script **nao instala nada** alem do Python: o gerador usa apenas bibliotecas
> padrao. Depois de gerar/enviar, o link **raw** da lista no GitHub continua o
> mesmo — e so recarregar no SS IPTV.
>
> **Fluxo sugerido:** gere no Brasil de vez em quando (catalogo completo) e deixe
> o GitHub Actions rodando a cada 6h para manter os links sempre validos.

## Observacoes

- O catalogo e definido pela regiao do IP que faz a coleta. O GitHub Actions
  roda em servidores nos EUA, entao a lista reflete o catalogo visto de fora do
  Brasil (predominantemente conteudo latino, em espanhol). Para gerar o
  catalogo exatamente como aparece no Brasil, rode o script `gerar_runtime_vod.py`
  em uma maquina com IP brasileiro e publique o resultado.
- Alguns titulos podem ter restricao geografica; a reproducao depende do seu pais.
- Os links sao regenerados a cada atualizacao, mantendo a lista sempre valida.
