#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador assíncrono de lista M3U — ComandoPlay.tv
Otimizado para SS IPTV (prioridade: MP4 progressivo muxado).

Ordem de preferência dos links:
  1. Mixdrop  → MP4 direto (vídeo+áudio no mesmo arquivo)  ← melhor p/ SS IPTV
  2. brstream → HLS master (pode ter áudio separado)
  3. Outros servidores / embed

Técnicas: asyncio + aiohttp, unpacker do packer do Mixdrop, helper Node.js.
Saída: playlists/comandoplay.m3u
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import aiohttp

# ===================== CONFIG =====================
BASE_URL = "https://comandoplay.tv"
MOVIES_CATEGORY = f"{BASE_URL}/category/movies-2/"
SERIES_CATEGORY = f"{BASE_URL}/category/tv-series/"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

INCLUDE_SERIES = False
CONCURRENCY_LIST = 8
CONCURRENCY_DETAIL = 14
CONCURRENCY_RESOLVE = 10
TIMEOUT = aiohttp.ClientTimeout(total=28, connect=12)
RETRIES = 3
USE_NODE_HELPER = True
MAX_PAGES = 0  # 0 = todas

# Preferência de qualidade para SS IPTV
# "mp4"  = prioriza Mixdrop MP4 (recomendado SS IPTV)
# "hls"  = prioriza brstream HLS
PREFER = "mp4"

# ==================================================

GENRE_MAP = {
    "acao": "Ação",
    "action-adventure": "Ação e Aventura",
    "animacao": "Animação",
    "aventura": "Aventura",
    "cinema-tv": "Cinema TV",
    "comedia": "Comédia",
    "crime": "Crime",
    "documentario": "Documentário",
    "drama": "Drama",
    "esporte": "Esporte",
    "familia": "Família",
    "fantasia": "Fantasia",
    "faroeste": "Faroeste",
    "ficcao-cientifica": "Ficção Científica",
    "guerra": "Guerra",
    "historia": "História",
    "kids": "Infantil",
    "misterio": "Mistério",
    "musica": "Música",
    "romance": "Romance",
    "suspense": "Suspense",
    "terror": "Terror",
    "thriller": "Suspense",
    "movies-2": None,
    "tv-series": None,
    "movies": None,
}


@dataclass
class MovieEntry:
    title: str
    logo: str
    genre: str
    page_url: str
    stream_url: str = ""
    stream_type: str = ""  # mp4 | hls | other
    servers: list = field(default_factory=list)
    embed: str = ""


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(",", " ").strip())


def normalize_genre(slug: str) -> Optional[str]:
    if not slug:
        return "Outros"
    key = slug.strip().lower()
    mapped = GENRE_MAP.get(key)
    if mapped is None:
        return None
    if mapped:
        return mapped
    return key.replace("-", " ").title()


def primary_genre(slugs: list) -> str:
    for s in slugs:
        g = normalize_genre(s)
        if g:
            return g
    return "Outros"


async def fetch(session, url, *, referer=None, retries=RETRIES, headers_extra=None):
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    if headers_extra:
        headers.update(headers_extra)
    last_exc = None
    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers, timeout=TIMEOUT) as resp:
                if resp.status == 404:
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=404, message="Not Found"
                    )
                resp.raise_for_status()
                return await resp.text(errors="ignore")
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.5 + attempt * 0.7)
    raise last_exc


def extract_listing_items(html):
    items = []
    for m in re.finditer(
        r'id="post-(\d+)"[^>]*>.*?<a\s+href="(https://comandoplay\.tv/[^"]+/)"',
        html,
        re.S | re.I,
    ):
        items.append((m.group(1), m.group(2)))
    if not items:
        for m in re.finditer(
            r'<a\s+href="(https://comandoplay\.tv/([a-z0-9-]+)/)"[^>]*>\s*<img',
            html,
            re.I,
        ):
            slug = m.group(2)
            if slug in ("blog", "category") or slug.startswith("page"):
                continue
            items.append((None, m.group(1)))
    return items


async def discover_max_page(session, category_url):
    html = await fetch(session, category_url)
    pages = [int(x) for x in re.findall(r"/page/(\d+)/", html)]
    if not pages:
        return 1
    low = max(pages)
    last_ok = low
    for p in range(low, low + 80):
        url = f"{category_url.rstrip('/')}/page/{p}/"
        try:
            await fetch(session, url, retries=1)
            last_ok = p
        except Exception:
            break
        await asyncio.sleep(0.1)
    return last_ok


async def collect_listing(session, category_url, label):
    print(f"Descobrindo páginas de {label}...")
    try:
        max_page = await discover_max_page(session, category_url)
    except Exception as e:
        print(f"  ! erro ao descobrir páginas: {e}", file=sys.stderr)
        max_page = 1
    if MAX_PAGES > 0:
        max_page = min(max_page, MAX_PAGES)
    print(f"  páginas: {max_page}")

    sem = asyncio.Semaphore(CONCURRENCY_LIST)
    seen = set()
    urls = []

    async def one_page(p):
        url = category_url if p == 1 else f"{category_url.rstrip('/')}/page/{p}/"
        async with sem:
            try:
                html = await fetch(session, url)
                return extract_listing_items(html)
            except Exception as e:
                print(f"  ! página {p}: {e}", file=sys.stderr)
                return []

    tasks = [one_page(p) for p in range(1, max_page + 1)]
    done = 0
    for coro in asyncio.as_completed(tasks):
        items = await coro
        for _, u in items:
            if u not in seen:
                seen.add(u)
                urls.append(u)
        done += 1
        if done % 15 == 0 or done == max_page:
            print(f"  listagem: {done}/{max_page} págs → {len(urls)} itens")

    print(f"  total {label}: {len(urls)}")
    return urls


def parse_detail_html(html, page_url):
    title = None
    m = re.search(r'<h1[^>]*class="[^"]*entry-title[^"]*"[^>]*>([^<]+)', html, re.I)
    if m:
        title = clean(m.group(1))
    if not title:
        m = re.search(r'itemprop="name"[^>]*>([^<]+)', html)
        if m:
            title = clean(m.group(1))
    if not title:
        m = re.search(r"<title>([^<]+)", html)
        if m:
            t = m.group(1)
            t = re.sub(r"\s*[-|].*Comando Play.*$", "", t, flags=re.I)
            t = re.sub(r"^Assistir\s+", "", t, flags=re.I)
            t = re.sub(r"\s+Online.*$", "", t, flags=re.I)
            title = clean(t)
    if not title:
        title = page_url.rstrip("/").split("/")[-1].replace("-", " ").title()

    logo = ""
    m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if m:
        logo = m.group(1)
    if not logo:
        m = re.search(r'(https://image\.tmdb\.org/t/p/[^"\']+)', html)
        if m:
            logo = m.group(1)

    cat_slugs = re.findall(r"/category/([a-z0-9-]+)/", html)
    genre = primary_genre(cat_slugs)

    embed_ids = re.findall(r"embedplay\.icu/player\.php\?id=([a-zA-Z0-9]+)", html)
    embed = f"https://embedplay.icu/player.php?id={embed_ids[0]}" if embed_ids else ""

    return MovieEntry(title=title, logo=logo, genre=genre, page_url=page_url, embed=embed)


async def fetch_detail(session, url):
    try:
        html = await fetch(session, url, referer=BASE_URL)
        return parse_detail_html(html, url)
    except Exception:
        return None


# -------------------- Mixdrop packer unpack --------------------

def unpack_packer(packed_js: str) -> Optional[str]:
    """Desempacota o packer clássico do Mixdrop (eval(function(p,a,c,k,e,d)...)."""
    m = re.search(
        r"}\('((?:\\'|[^'])*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:\\'|[^'])*)'\.split\('\|'\)",
        packed_js,
    )
    if not m:
        # variante com aspas duplas / formato um pouco diferente
        m = re.search(
            r"}\(\"((?:\\\"|[^\"])*)\"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*\"((?:\\\"|[^\"])*)\"\.split\('\|'\)",
            packed_js,
        )
    if not m:
        return None
    payload, _a, c_str, keys_str = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        c = int(c_str)
    except ValueError:
        return None
    # unescape mínimo
    payload = payload.replace("\\'", "'").replace('\\"', '"')
    keys = keys_str.split("|")
    # substitui do maior índice para o menor para não corromper números
    out = payload
    for i in range(c - 1, -1, -1):
        if i < len(keys) and keys[i]:
            out = re.sub(rf"\b{i}\b", keys[i], out)
    return out


def extract_mixdrop_mp4(html: str) -> Optional[str]:
    """Extrai URL MP4 direta da página de embed do Mixdrop."""
    # 1) tenta unpack do packer
    for m in re.finditer(r"eval\(function\(p,a,c,k,e,d\)[\s\S]*?\.split\('\|'\)[\s\S]*?\)\)", html):
        unpacked = unpack_packer(m.group(0))
        if not unpacked:
            continue
        # MDCore.wurl="//host/v2/id.mp4?s=...&e=...&_t=..."
        w = re.search(r"""MDCore\.wurl\s*=\s*["']([^"']+)["']""", unpacked)
        if w:
            url = w.group(1)
            if url.startswith("//"):
                url = "https:" + url
            if ".mp4" in url:
                return url
    # 2) fallback: procura URL mxcontent / mp4 já visível
    for pat in [
        r"""MDCore\.wurl\s*=\s*["']([^"']+)["']""",
        r"""(https?:)?//[^"'\\s]+mxcontent\.net[^"'\\s]+\.mp4[^"'\\s]*""",
        r"""(https?:)?//[^"'\\s]+\.mp4\?[^"'\\s]+""",
    ]:
        m = re.search(pat, html)
        if m:
            url = m.group(1) if m.lastindex and m.group(1) and m.group(1).startswith("http") else m.group(0)
            if url.startswith("//"):
                url = "https:" + url
            if ".mp4" in url:
                return url
    return None


async def resolve_mixdrop(session, mix_url: str) -> Optional[str]:
    try:
        html = await fetch(session, mix_url, referer="https://embedplay.icu/")
        return extract_mixdrop_mp4(html)
    except Exception:
        return None


# -------------------- brstream HLS --------------------

BRSTREAM_VIDEO_RE = re.compile(r"var\s+video\s*=\s*(\{.*?\});", re.S)


def build_brstream_hls(video) -> Optional[str]:
    try:
        uid = video.get("uid")
        md5 = video.get("md5")
        vid = video.get("id")
        status = video.get("status", "1")
        if not (uid and md5 and vid):
            return None
        return (
            f"https://watch.brstream.cc/m3u8/{uid}/{md5}/master.txt"
            f"?s=1&id={vid}&cache={status}"
        )
    except Exception:
        return None


async def resolve_brstream(session, watch_url: str) -> Optional[str]:
    try:
        html = await fetch(session, watch_url, referer="https://embedplay.icu/")
        m = BRSTREAM_VIDEO_RE.search(html)
        if m:
            video = json.loads(m.group(1))
            return build_brstream_hls(video)
        uid = re.search(r'"uid"\s*:\s*"([^"]+)"', html)
        md5 = re.search(r'"md5"\s*:\s*"([^"]+)"', html)
        vid = re.search(r'"id"\s*:\s*"([^"]+)"', html)
        if uid and md5 and vid:
            return build_brstream_hls(
                {"uid": uid.group(1), "md5": md5.group(1), "id": vid.group(1), "status": "1"}
            )
    except Exception:
        pass
    return None


async def list_servers_from_embed(session, embed_url: str) -> list:
    servers = []
    try:
        html = await fetch(session, embed_url, referer=BASE_URL)
        for u in re.findall(r"playVideo\(['\"](https?://[^'\"]+)['\"]\)", html):
            if u not in servers:
                servers.append(u)
    except Exception:
        pass
    return servers


def node_resolve(url: str) -> Optional[str]:
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolve_stream.js")
    if not os.path.isfile(helper):
        return None
    try:
        r = subprocess.run(
            ["node", helper, url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip().startswith("http"):
            return r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return None


async def resolve_stream(session, entry: MovieEntry) -> MovieEntry:
    if not entry.embed:
        return entry

    servers = await list_servers_from_embed(session, entry.embed)
    entry.servers = servers

    mix = next((u for u in servers if "mixdrop" in u), None)
    brs = next((u for u in servers if "brstream" in u), None)

    mp4_url = None
    hls_url = None

    if mix:
        mp4_url = await resolve_mixdrop(session, mix)
    if brs:
        hls_url = await resolve_brstream(session, brs)

    # Escolha conforme preferência (SS IPTV → mp4 primeiro)
    if PREFER == "mp4":
        chosen = mp4_url or hls_url
        stype = "mp4" if mp4_url else ("hls" if hls_url else "")
    else:
        chosen = hls_url or mp4_url
        stype = "hls" if hls_url else ("mp4" if mp4_url else "")

    if not chosen and USE_NODE_HELPER:
        node_url = await asyncio.to_thread(node_resolve, entry.embed)
        if node_url:
            chosen = node_url
            stype = "mp4" if ".mp4" in node_url else "hls"

    if not chosen and servers:
        chosen = servers[0]
        stype = "other"

    entry.stream_url = chosen or entry.embed or ""
    entry.stream_type = stype
    return entry


# -------------------- Main --------------------

async def run(max_pages=0, include_series=False, prefer="mp4"):
    global MAX_PAGES, INCLUDE_SERIES, PREFER
    if max_pages:
        MAX_PAGES = max_pages
    INCLUDE_SERIES = include_series
    PREFER = prefer

    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists")
    os.makedirs(outdir, exist_ok=True)

    connector = aiohttp.TCPConnector(limit=36, ssl=False, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        movie_urls = await collect_listing(session, MOVIES_CATEGORY, "Filmes")
        series_urls = []
        if INCLUDE_SERIES:
            series_urls = await collect_listing(session, SERIES_CATEGORY, "Séries")

        series_set = set(series_urls)
        all_urls = []
        seen = set()
        for u in movie_urls + series_urls:
            if u not in seen:
                seen.add(u)
                all_urls.append(u)

        print(f"\nColetando detalhes de {len(all_urls)} páginas...")
        sem = asyncio.Semaphore(CONCURRENCY_DETAIL)
        entries = []

        async def detail_one(url):
            async with sem:
                return await fetch_detail(session, url)

        done = failed = 0
        for coro in asyncio.as_completed([detail_one(u) for u in all_urls]):
            e = await coro
            done += 1
            if e:
                entries.append(e)
            else:
                failed += 1
            if done % 100 == 0 or done == len(all_urls):
                print(f"  detalhes: {done}/{len(all_urls)} (ok={len(entries)}, falha={failed})")

        print(f"\nResolvendo streams (prefer={PREFER}) de {len(entries)} itens...")
        sem_r = asyncio.Semaphore(CONCURRENCY_RESOLVE)

        async def resolve_one(e):
            async with sem_r:
                return await resolve_stream(session, e)

        resolved = []
        done = mp4_n = hls_n = 0
        for coro in asyncio.as_completed([resolve_one(e) for e in entries]):
            e = await coro
            resolved.append(e)
            if e.stream_type == "mp4":
                mp4_n += 1
            elif e.stream_type == "hls":
                hls_n += 1
            done += 1
            if done % 60 == 0 or done == len(entries):
                print(f"  resolve: {done}/{len(entries)} (MP4={mp4_n}, HLS={hls_n})")

    seen_s = set()
    final = []
    for e in resolved:
        if not e.stream_url or e.stream_url in seen_s:
            continue
        seen_s.add(e.stream_url)
        is_series = e.page_url in series_set
        tipo = "Series" if is_series else "Filmes"
        grupo = f"Series • {e.genre} • {e.title}" if is_series else f"Filmes • {e.genre}"
        sortkey = (tipo, e.genre.lower(), e.title.lower())
        final.append((grupo, sortkey, e.title, e.stream_url, e.logo, e.stream_type))

    final.sort(key=lambda x: x[1])

    out_path = os.path.join(outdir, "comandoplay.m3u")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        # SS IPTV ignora EXTVLCOPT na maioria das builds; mantemos para VLC
        f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
        for grupo, _sk, title, url, logo, stype in final:
            attrs = f'tvg-name="{title}" group-title="{grupo}"'
            if logo:
                attrs += f' tvg-logo="{logo}"'
            f.write(f"#EXTINF:-1 {attrs},{title}\n")
            # Referer ajuda Mixdrop/brstream em players que respeitam
            if "mixdrop" in url or "mxcontent" in url:
                f.write("#EXTVLCOPT:http-referrer=https://mixdrop.top/\n")
            elif "brstream" in url:
                f.write("#EXTVLCOPT:http-referrer=https://watch.brstream.cc/\n")
            f.write(f"{url}\n")

    grupos = sorted({x[0] for x in final})
    print(f"\nOK: {len(final)} itens em {len(grupos)} grupos → {out_path}")
    print(f"   MP4 (Mixdrop): {mp4_n}  |  HLS (brstream): {hls_n}")
    print("   Dica SS IPTV: priorize itens MP4; HLS com áudio separado pode ficar sem som.")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Gera M3U do ComandoPlay (otimizado SS IPTV)")
    parser.add_argument("--pages", type=int, default=0, help="Limitar páginas (0=todas)")
    parser.add_argument("--series", action="store_true", help="Incluir séries")
    parser.add_argument(
        "--prefer",
        choices=("mp4", "hls"),
        default="mp4",
        help="Preferir MP4 (SS IPTV) ou HLS",
    )
    args = parser.parse_args()

    t0 = time.time()
    asyncio.run(run(max_pages=args.pages, include_series=args.series, prefer=args.prefer))
    print(f"Tempo total: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
