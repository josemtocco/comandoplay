import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

BASE_URL = "https://comandoplay.tv/category/movies-2/"
STATE_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u8"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def scrape_channels():
    """Percorre todas as páginas de /category/movies-2/ e coleta os filmes."""
    channels = []
    seen_urls = set()
    page = 1
    max_empty = 2
    empty_count = 0

    while True:
        if page == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}page/{page}/"

        print(f"Coletando página {page}... ({url})")
        try:
            response = SESSION.get(url, timeout=20)
            if response.status_code == 404:
                print(f"Página {page} não existe (404). Finalizando.")
                break
            response.raise_for_status()
        except Exception as e:
            print(f"Erro ao buscar página {page}: {e}")
            empty_count += 1
            if empty_count >= max_empty:
                break
            page += 1
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select("div.item.normal")

        if not items:
            print(f"Nenhum filme encontrado na página {page}.")
            empty_count += 1
            if empty_count >= max_empty:
                print("Finalizando paginação.")
                break
            page += 1
            continue

        empty_count = 0
        page_channels = []

        for item in items:
            a = item.find("a", href=True)
            if not a:
                continue

            href = a["href"].strip()
            full_url = href if href.startswith("http") else urljoin("https://comandoplay.tv", href)

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            name_tag = item.select_one("h2.movie-title")
            name = name_tag.get_text(strip=True) if name_tag else a.get("title") or "Filme Desconhecido"

            logo = ""
            img = item.find("img")
            if img:
                logo = img.get("data-src") or img.get("src") or ""
                if logo.startswith("data:"):
                    logo = img.get("data-src") or ""

            quality_tag = item.select_one(".item-quality")
            quality = quality_tag.get_text(strip=True) if quality_tag else ""
            group = quality if quality else "Filmes"

            page_channels.append({
                "name": name,
                "page_url": full_url,
                "logo": logo,
                "group": group,
            })

        print(f"  → {len(page_channels)} filmes nesta página (total acumulado: {len(channels) + len(page_channels)})")
        channels.extend(page_channels)
        page += 1
        time.sleep(0.35)

    return channels


def resolve_brstream(watch_url: str) -> list[tuple[str, str]]:
    """
    A partir de uma URL watch.brstream.cc, retorna lista de (rótulo, url)
    com TODAS as variantes de qualidade (ex: 720p, 480p, 240p).
    """
    try:
        r = SESSION.get(watch_url, timeout=15)
        r.raise_for_status()
        html = r.text

        m = re.search(r'var\s+video\s*=\s*(\{.*?\});', html, re.S)
        if not m:
            return []

        vid = m.group(1)
        uid = re.search(r'"uid"\s*:\s*"([^"]+)"', vid)
        md5 = re.search(r'"md5"\s*:\s*"([^"]+)"', vid)
        vid_id = re.search(r'"id"\s*:\s*"([^"]+)"', vid)

        if not (uid and md5 and vid_id):
            return []

        master_url = (
            f"https://watch.brstream.cc/m3u8/{uid.group(1)}/{md5.group(1)}"
            f"/master.txt?s=1&id={vid_id.group(1)}&cache=1"
        )

        r2 = SESSION.get(master_url, timeout=10)
        if r2.status_code != 200 or not r2.text.lstrip().startswith("#EXTM3U"):
            return [("auto", master_url)]

        variants = []
        lines = r2.text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#EXT-X-STREAM-INF:"):
                res_m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                bw_m = re.search(r"BANDWIDTH=(\d+)", line)
                height = res_m.group(1) if res_m else None
                bw = int(bw_m.group(1)) if bw_m else 0

                j = i + 1
                while j < len(lines) and (lines[j].startswith("#") or not lines[j].strip()):
                    j += 1
                if j >= len(lines):
                    i += 1
                    continue

                uri = lines[j].strip()
                if uri.startswith("/"):
                    uri = "https://watch.brstream.cc" + uri

                if height:
                    label = f"{height}p"
                elif bw >= 1200000:
                    label = "720p"
                elif bw >= 600000:
                    label = "480p"
                else:
                    label = "240p"

                variants.append((label, uri))
            i += 1

        # Ordena do maior para o menor (720p primeiro)
        def sort_key(item):
            label = item[0]
            try:
                return -int(label.replace("p", ""))
            except ValueError:
                return 0

        variants.sort(key=sort_key)

        # Remove duplicatas de label (mantém a primeira = maior bw)
        seen = set()
        unique = []
        for label, uri in variants:
            if label not in seen:
                seen.add(label)
                unique.append((label, uri))

        return unique if unique else [("auto", master_url)]
    except Exception:
        return []


def extract_stream_url(page_html: str) -> list[tuple[str, str]]:
    """
    Cadeia de resolução:
    1. Página do filme → embedplay.icu (ou links diretos de hosters)
    2. Página embedplay → lista de servidores (playVideo)
    3. Servidor PRINCIPAL (preferencialmente brstream) → todas as variantes

    Retorna lista de (rótulo, url), ex: [("720p", "..."), ("480p", "...")]
    """
    embed_urls = re.findall(
        r'https?://(?:www\.)?embedplay\.icu/player\.php\?id=[a-f0-9]+',
        page_html,
        re.IGNORECASE,
    )

    other_hosters = re.findall(
        r'https?://(?:www\.)?(?:mixdrop|morencius|dood|streamtape|filemoon)\.[^\s"\'<>]+',
        page_html,
        re.IGNORECASE,
    )

    # Prioridade: embedplay → brstream → todas as variantes
    for embed in embed_urls:
        try:
            r = SESSION.get(embed, timeout=12)
            if r.status_code != 200:
                continue
            html = r.text

            servers = re.findall(r"playVideo\(['\"]([^'\"]+)['\"]\)", html)

            principal_m = re.search(
                r"playVideo\(['\"]([^'\"]+)['\"]\)[^>]*>\s*PRINCIPAL",
                html,
                re.IGNORECASE,
            )
            ordered = []
            if principal_m:
                ordered.append(principal_m.group(1))
            for s in servers:
                if s not in ordered:
                    ordered.append(s)

            for server_url in ordered:
                if "brstream.cc" in server_url or "watch.brstream" in server_url:
                    variants = resolve_brstream(server_url)
                    if variants:
                        return variants
        except Exception:
            continue

    # Fallback: um único hoster genérico
    candidates = other_hosters
    if candidates:
        return [("auto", candidates[0])]

    direct = re.findall(
        r'(https?://[^\s\'"<>]+?\.(?:m3u8?|mp4)(?:\?[^\s\'"<>]*)?)',
        page_html,
        re.IGNORECASE,
    )
    if direct:
        return [("auto", direct[0])]

    return []


def validate_stream(url: str) -> bool:
    """Valida se a URL parece ser um stream utilizável."""
    if not url:
        return False

    # URLs do brstream (master ou variante 720p/480p/etc.)
    if "watch.brstream.cc/" in url and ("/m3u8/" in url or "/stream/" in url):
        try:
            r = SESSION.get(url, timeout=10, allow_redirects=True)
            if r.status_code == 200 and r.text.lstrip().startswith("#EXTM3U"):
                return True
            return r.status_code == 200
        except Exception:
            return True

    # Outros hosters: aceita se a URL for bem formada
    hoster_domains = (
        "mixdrop", "morencius", "embedplay", "dood", "streamtape",
        "filemoon", "upstream", "vidcloud", "voe", "lulustream", "brstream",
    )
    if any(d in url.lower() for d in hoster_domains):
        return True

    # Direto m3u8/mp4
    try:
        r = SESSION.head(url, timeout=8, allow_redirects=True)
        if r.status_code == 405 or not r.headers.get("Content-Type"):
            r = SESSION.get(url, headers={**HEADERS, "Range": "bytes=0-1024"}, timeout=8, stream=True)
        ct = r.headers.get("Content-Type", "").lower()
        if "video/" in ct or "mpegurl" in ct:
            return True
        if "octet-stream" in ct and re.search(r"\.mp4(\?|$)", url, re.I):
            return True
    except Exception:
        pass
    return False


def process_scraped_channel(channel_info):
    """Retorna lista de entradas (uma por variante) ou lista vazia."""
    name = channel_info["name"]
    page_url = channel_info["page_url"]
    entries = []

    try:
        response = SESSION.get(page_url, timeout=15)
        response.raise_for_status()
        variants = extract_stream_url(response.text)
    except Exception as e:
        print(f"  Erro ao processar '{name}': {e}")
        variants = []

    for label, stream_url in variants:
        if not stream_url or not validate_stream(stream_url):
            continue
        entry_name = name if label == "auto" else f"{name} [{label}]"
        entries.append({
            "name": entry_name,
            "base_name": name,
            "quality": label,
            "stream_url": stream_url,
            "logo": channel_info.get("logo", ""),
            "group": channel_info.get("group", "Filmes"),
            "page_url": page_url,
            "is_active": True,
        })

    return entries


def process_existing_channel(name, info):
    """Revalida uma entrada já existente (pode ser variante)."""
    stream_url = info.get("stream_url")
    is_active = bool(stream_url) and validate_stream(stream_url)

    return [{
        "name": name,
        "base_name": info.get("base_name", name.split(" [")[0]),
        "quality": info.get("quality", "auto"),
        "stream_url": stream_url,
        "logo": info.get("logo", ""),
        "group": info.get("group", "Filmes"),
        "page_url": info.get("page_url", ""),
        "is_active": is_active,
    }]


def generate_m3u8(state):
    lines = ["#EXTM3U"]

    channels_list = []
    for name, info in state.items():
        info_dict = info.copy()
        info_dict["name"] = name
        channels_list.append(info_dict)

    # Ordena por grupo, nome base e qualidade (720p antes de 480p etc.)
    def sort_key(x):
        group = x.get("group", "Filmes")
        base = x.get("base_name", x.get("name", ""))
        q = x.get("quality", "auto")
        try:
            q_num = -int(q.replace("p", ""))
        except ValueError:
            q_num = 0
        return (group, base, q_num)

    sorted_channels = sorted(channels_list, key=sort_key)

    active_count = 0
    for ch in sorted_channels:
        if not ch.get("stream_url"):
            continue

        logo = ch.get("logo", "")
        group = ch.get("group", "Filmes").replace('"', '\\"')
        name = ch["name"].replace('"', '\\"')
        url = ch["stream_url"]

        extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}'
        lines.append(extinf)
        lines.append("#EXTSIZE: medium")
        lines.append(url)
        active_count += 1

    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Sucesso! {PLAYLIST_FILE} gerado com {active_count} entradas (todas as variantes).")


def main():
    print("Carregando estado anterior...")
    state = load_state()

    print("Coletando filmes do site...")
    scraped_channels = scrape_channels()
    print(f"Encontrados {len(scraped_channels)} filmes no site.")

    scraped_base_names = {ch["name"] for ch in scraped_channels}
    tasks = []

    for ch in scraped_channels:
        tasks.append(("scraped", ch))

    # Mantém entradas antigas cujo filme base sumiu do site
    for name, info in state.items():
        base = info.get("base_name", name.split(" [")[0])
        if base not in scraped_base_names:
            tasks.append(("existing", {"name": name, "info": info}))

    print(f"Processando {len(tasks)} itens (todas as variantes + validação)...")
    new_state = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_task = {}
        for task in tasks:
            if task[0] == "scraped":
                future = executor.submit(process_scraped_channel, task[1])
            else:
                future = executor.submit(
                    process_existing_channel, task[1]["name"], task[1]["info"]
                )
            future_to_task[future] = task

        done = 0
        for future in as_completed(future_to_task):
            results = future.result()  # agora é uma lista
            done += 1
            if done % 30 == 0 or done == len(tasks):
                print(f"  Progresso: {done}/{len(tasks)}")

            for result in results:
                if result.get("is_active") and result.get("stream_url"):
                    new_state[result["name"]] = {
                        "stream_url": result["stream_url"],
                        "logo": result["logo"],
                        "group": result["group"],
                        "page_url": result["page_url"],
                        "base_name": result.get("base_name", result["name"]),
                        "quality": result.get("quality", "auto"),
                    }

    print(f"Mantidas {len(new_state)} entradas com stream válido (todas as variantes).")
    save_state(new_state)
    generate_m3u8(new_state)


if __name__ == "__main__":
    main()
