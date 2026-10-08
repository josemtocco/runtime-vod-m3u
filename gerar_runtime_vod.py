#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de lista M3U com o conteudo sob demanda (VOD) do Runtime.tv
(plataforma OTTera). Coleta Filmes e Series, extrai o entryId Kaltura
de cada video e monta URLs HLS diretas, reproduziveis em VLC / SS IPTV.

Organizacao: itens separados por GENERO.
  - Filmes:  group-title = "Filmes \u2022 <Genero>"
  - Series:  group-title = "Series \u2022 <Genero> \u2022 <Nome da serie>"
             (mantem cada serie agrupada dentro do seu genero)

Saida: playlists/runtime_vod.m3u
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://api-ott.runtime.tv"
HOME = "https://www.runtime.tv/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERRER = "runtime.tv"

MOVIES_PARENT = "797"     # secao Movies -> catalogo completo de filmes
SERIES_PARENT = "18107"   # secao Series -> todas as series

PAGE = 100
MAX_WORKERS = 12
TIMEOUT = 40

# Filtrar apenas conteudo em portugues (pt / pt-br).
# Observacao: o catalogo depende da regiao do IP que coleta. Rodando fora do
# Brasil (ex.: GitHub Actions nos EUA) aparecem poucos titulos em portugues;
# rodando de um IP brasileiro o catalogo em portugues fica completo.
ONLY_PORTUGUESE = True

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

BASE = {
    "version": "13",
    "device_type": "desktop",
    "platform": "web",
    "partner": "internal",
    "language": "en",
}

# ---- Normalizacao de generos (varios idiomas) para portugues ----
GENRE_MAP = {
    "dramatico": "Drama", "drama": "Drama",
    "documental": "Documentario", "documentary": "Documentario",
    "documentario": "Documentario", "documentary film": "Documentario",
    "accion": "Acao", "action": "Acao", "acao": "Acao",
    "thriller": "Suspense", "suspense": "Suspense",
    "comedia": "Comedia", "comedy": "Comedia",
    "romance": "Romance",
    "crimen": "Crime", "crime": "Crime",
    "terror": "Terror", "horror": "Terror",
    "familia": "Familia", "family": "Familia", "kids": "Infantil",
    "scifi": "Ficcao Cientifica", "sci-fi": "Ficcao Cientifica",
    "science fiction": "Ficcao Cientifica", "ciencia ficcion": "Ficcao Cientifica",
    "aventura": "Aventura", "adventure": "Aventura",
    "reality": "Reality",
    "animation": "Animacao", "animacion": "Animacao", "animacao": "Animacao",
    "historia": "Historia", "history": "Historia",
    "de vaqueros": "Faroeste", "western": "Faroeste",
    "news": "Noticias",
    "entertainment": "Entretenimento",
    "fantasy": "Fantasia", "fantasia": "Fantasia",
    "guerra": "Guerra", "war": "Guerra",
    "musica": "Musica", "music": "Musica",
    "deportes": "Esportes", "sports": "Esportes",
    "comedy/romance": "Comedia",
    "faith": "Religioso",
}


def strip_accents(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalize_genre(name):
    if not name:
        return "Outros"
    key = strip_accents(name).strip().lower()
    return GENRE_MAP.get(key, name.strip())


def primary_genre(obj):
    mc = (obj.get("meta") or {}).get("categories") or []
    if isinstance(mc, list) and mc:
        return normalize_genre(mc[0].get("name"))
    return "Outros"


def is_portuguese(obj):
    meta = obj.get("meta") or {}
    code = (meta.get("langcode") or "").lower()
    lang = (meta.get("language") or "").lower()
    url = (obj.get("url") or "").lower()
    return (code.startswith("pt")
            or "portugu" in lang
            or url.startswith("/pt"))


def http_get(url, headers, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=CTX, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(1 + i)
    raise last


def get_cs_auth_token():
    html = http_get(HOME, {"User-Agent": UA}).decode("utf-8", "ignore")
    m = re.search(r'"cs_auth_token"\s*:\s*"([^"]+)"', html)
    if not m:
        raise RuntimeError("cs_auth_token nao encontrado na home")
    return m.group(1)


def api_headers(token):
    return {"User-Agent": UA, "ottera-cs-auth": token, "ottera-referrer": REFERRER}


def call(ep, params, headers):
    q = urllib.parse.urlencode({**BASE, **params})
    return json.loads(http_get(f"{API}/{ep}?{q}", headers))


def fetch_all_referenced(parent_id, object_type, headers, order=None, extra=None):
    out, start, total = [], 0, None
    while True:
        p = {
            "image_width": 366, "image_format": "widescreen",
            "parent_id": parent_id, "parent_type": "collection",
            "object_type": object_type, "strip_content_ratings": 1,
            "max": PAGE, "start": start,
        }
        if order:
            p["order"] = order
        if extra:
            p.update(extra)
        try:
            r = call("getreferencedobjects", p, headers)
        except Exception as e:
            print(f"  ! erro parent={parent_id} start={start}: {e}", file=sys.stderr)
            break
        objs = r.get("objects", []) or []
        if total is None:
            total = int(r.get("total_results", 0) or 0)
        out.extend(objs)
        start += len(objs)
        if not objs or start >= total:
            break
        time.sleep(0.05)
    return out


def fetch_show_videos(show_id, headers):
    out, start, total = [], 0, None
    while True:
        p = {
            "image_width": 366, "image_format": "widescreen",
            "parent_id": show_id, "parent_type": "show",
            "object_type": "video", "parent_meta": 1,
            "max": PAGE, "start": start,
        }
        try:
            r = call("getreferencedobjects", p, headers)
        except Exception:
            break
        objs = r.get("objects", []) or []
        if total is None:
            total = int(r.get("total_results", 0) or 0)
        out.extend(objs)
        start += len(objs)
        if not objs or start >= total:
            break
        time.sleep(0.03)
    return out


ENTRY_RE = re.compile(r'(?:entryId|entry_id)/(\d+_[a-zA-Z0-9]+)')
PSP_RE = re.compile(r'/p/(\d+)/sp/(\d+)/')


def extract_kaltura(video):
    eid = p = sp = None
    for v in video.values():
        if not isinstance(v, str) or "kaltura.com" not in v:
            continue
        if eid is None:
            m = ENTRY_RE.search(v)
            if m:
                eid = m.group(1)
        if p is None:
            m = PSP_RE.search(v)
            if m:
                p, sp = m.group(1), m.group(2)
        if eid and p:
            break
    return eid, p, sp


FLAVOR_IN_URL = re.compile(r'flavorId/(\d+_[a-zA-Z0-9]+)')


def hls_url(eid, p, sp, flavor_ids=None):
    base = f"https://cfvod.kaltura.com/p/{p}/sp/{sp}/playManifest/entryId/{eid}"
    if flavor_ids:
        return (base + f"/flavorIds/{','.join(flavor_ids)}"
                       "/format/applehttp/protocol/https/a.m3u8")
    return base + "/format/applehttp/protocol/https/a.m3u8"


_flavor_cache = {}


def video_flavor_ids(eid, p, sp):
    """Busca o master HLS e devolve SOMENTE os flavorIds de VIDEO (variantes
    com RESOLUTION). Exclui a variante somente-audio (BANDWIDTH baixo, sem
    RESOLUTION) que faz players simples (SS IPTV) tocarem 'so audio, sem
    imagem'. As variantes de video do Runtime/Kaltura ja sao muxadas
    (video H264 + audio AAC no mesmo segmento)."""
    if eid in _flavor_cache:
        return _flavor_cache[eid]
    ids = []
    try:
        master = http_get(hls_url(eid, p, sp),
                          {"User-Agent": UA}).decode("utf-8", "ignore")
        lines = master.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("#EXT-X-STREAM-INF") and "RESOLUTION=" in ln:
                for nxt in lines[i + 1:]:
                    if nxt and not nxt.startswith("#"):
                        m = FLAVOR_IN_URL.search(nxt)
                        if m and m.group(1) not in ids:
                            ids.append(m.group(1))
                        break
    except Exception:
        ids = []
    _flavor_cache[eid] = ids
    return ids


def stream_url(eid, p, sp):
    """URL HLS final, com a correcao de so-audio aplicada quando possivel."""
    return hls_url(eid, p, sp, video_flavor_ids(eid, p, sp) or None)


def clean(s):
    return re.sub(r'\s+', ' ', (s or "").replace(',', ' ').strip())


def main():
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists")
    os.makedirs(outdir, exist_ok=True)

    token = get_cs_auth_token()
    headers = api_headers(token)
    print(f"cs_auth_token: {token[:6]}... ok")

    print("Coletando catalogo de Filmes...")
    movies = fetch_all_referenced(MOVIES_PARENT, "show,video", headers,
                                  order="mostpopular",
                                  extra={"video_type": "non_episode"})
    print(f"  filmes/objetos: {len(movies)}")
    print("Coletando catalogo de Series...")
    series = fetch_all_referenced(SERIES_PARENT, "show", headers)
    print(f"  series: {len(series)}")

    # Uniao de todo o catalogo (sem distinguir colecao). A classificacao
    # Filme x Serie e feita depois pelo numero de episodios.
    top = {}
    for o in movies:
        top.setdefault(o["id"], o)
    for o in series:
        top.setdefault(o["id"], o)
    print(f"Objetos unicos de topo: {len(top)}")

    direct_videos = []   # (video_obj, nome, genero)  -> sempre Filme
    shows = []           # (show_obj, genero)         -> tipo definido depois
    for oid, o in top.items():
        if ONLY_PORTUGUESE and not is_portuguese(o):
            continue
        genero = primary_genre(o)
        if o.get("type") == "video":
            direct_videos.append((o, clean(o.get("name")), genero))
        else:
            shows.append((o, genero))
    if ONLY_PORTUGUESE:
        print(f"Filtro portugues: {len(direct_videos)} filmes avulsos + "
              f"{len(shows)} series/novelas selecionados")

    print(f"Buscando episodios de {len(shows)} shows...")
    entries = []  # (grupo, chave_ordenacao, titulo, url, logo)

    def work(item):
        """Processa um show: baixa episodios e ja resolve a URL de video
        muxada (correcao so-audio) de cada um, em paralelo."""
        show, genero = item
        vids = fetch_show_videos(show["id"], headers)
        sname = clean(show.get("name"))
        single = len(vids) == 1
        tipo = "Filmes" if single else "Series"   # 1 ep -> Filme ; varios -> Serie
        out = []
        for v in vids:
            eid, p, sp = extract_kaltura(v)
            if not (eid and p and sp):
                continue
            vname = clean(v.get("name"))
            if single or not vname or vname.lower() == sname.lower():
                title = sname
            else:
                title = f"{sname} - {vname}"
            logo = v.get("widescreen_thumbnail_url") or v.get("thumbnail_url") or ""
            if tipo == "Series":
                grupo = f"Series \u2022 {genero} \u2022 {sname}"
            else:
                grupo = f"Filmes \u2022 {genero}"
            sortkey = (tipo, genero.lower(), sname.lower(), title.lower())
            out.append((grupo, sortkey, title, stream_url(eid, p, sp), logo))
        return out

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(work, it) for it in shows]
        for fut in as_completed(futs):
            entries.extend(fut.result())
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(shows)} shows processados...")

    def work_direct(triple):
        v, name, genero = triple
        eid, p, sp = extract_kaltura(v)
        if not (eid and p and sp):
            return None
        logo = v.get("widescreen_thumbnail_url") or v.get("thumbnail_url") or ""
        grupo = f"Filmes \u2022 {genero}"
        title = name or "Sem titulo"
        sortkey = ("Filmes", genero.lower(), title.lower(), "")
        return (grupo, sortkey, title, stream_url(eid, p, sp), logo)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for r in ex.map(work_direct, direct_videos):
            if r:
                entries.append(r)

    # dedupe por URL
    seen, uniq = set(), []
    for e in entries:
        if e[3] in seen:
            continue
        seen.add(e[3])
        uniq.append(e)
    uniq.sort(key=lambda e: e[1])

    out_path = os.path.join(outdir, "runtime_vod.m3u")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for grupo, _sk, title, url, logo in uniq:
            attrs = f'tvg-name="{title}" group-title="{grupo}"'
            if logo:
                attrs += f' tvg-logo="{logo}"'
            f.write(f"#EXTINF:-1 {attrs},{title}\n{url}\n")

    grupos = sorted({e[0] for e in uniq})
    print(f"\nOK: {len(uniq)} itens VOD em {len(grupos)} grupos -> {out_path}")
    return out_path


if __name__ == "__main__":
    main()
