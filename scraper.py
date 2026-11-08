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

# Hosters conhecidos usados pelo site (ordem de preferência)
HOSTER_PATTERNS = [
    r'https?://(?:www\.)?embedplay\.icu/[^\s"\'<>]+',
    r'https?://(?:www\.)?mixdrop\.(?:top|co|ag|to|sx|bz|ch|gl|vc|ms|my|io|click)/[^\s"\'<>]+',
    r'https?://(?:www\.)?morencius\.com/[^\s"\'<>]+',
    r'https?://(?:www\.)?(?:dood|doodstream)\.(?:to|watch|so|pm|wf|re|yt|sh|la)/[^\s"\'<>]+',
    r'https?://(?:www\.)?(?:streamtape|streamvid|filemoon|upstream|vidcloud|voe|lulustream)\.[^\s"\'<>]+',
]

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
    max_empty = 2  # para de buscar após 2 páginas vazias seguidas
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

            # Título
            name_tag = item.select_one("h2.movie-title")
            name = name_tag.get_text(strip=True) if name_tag else a.get("title") or "Filme Desconhecido"

            # Logo (preferir data-src por causa do lazy-load)
            logo = ""
            img = item.find("img")
            if img:
                logo = img.get("data-src") or img.get("src") or ""
                if logo.startswith("data:"):
                    logo = img.get("data-src") or ""

            # Qualidade / grupo
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

        # Pequena pausa para não sobrecarregar o servidor
        time.sleep(0.4)

    return channels


def extract_stream_url(html: str) -> str | None:
    """Extrai a melhor URL de hoster/stream da página do filme."""
    # 1) Tenta achar links de hosters conhecidos
    found = []
    for pattern in HOSTER_PATTERNS:
        matches = re.findall(pattern, html, re.IGNORECASE)
        found.extend(matches)

    if found:
        # Preferir o que estiver marcado como PRINCIPAL se possível
        principal = re.search(
            r'href=["\']([^"\']+)["\'][^>]*>\s*PRINCIPAL',
            html,
            re.IGNORECASE,
        )
        if principal:
            return principal.group(1)

        # Caso contrário, o primeiro da lista de preferência
        return found[0]

    # 2) Fallback: qualquer .m3u8 / .mp4
    video_pattern = re.compile(
        r'(https?://[^\s\'"<>]+?\.(?:m3u8?|mp4)(?:\?[^\s\'"<>]*)?)',
        re.IGNORECASE,
    )
    m3u8_urls = video_pattern.findall(html)
    if m3u8_urls:
        return m3u8_urls[0]

    return None


def validate_stream(url: str) -> bool:
    """
    Validação leve:
    - Para hosters conhecidos: considera ativo se a URL for bem formada.
    - Para .m3u8/.mp4: tenta HEAD/GET e verifica Content-Type.
    """
    if not url:
        return False

    # Hosters: não fazemos HEAD pesado (muitos bloqueiam ou usam JS)
    hoster_domains = (
        "mixdrop", "morencius", "embedplay", "dood", "streamtape",
        "filemoon", "upstream", "vidcloud", "voe", "lulustream", "streamvid",
    )
    if any(d in url.lower() for d in hoster_domains):
        return True

    try:
        res = SESSION.head(url, timeout=10, allow_redirects=True)
        if res.status_code == 405 or not res.headers.get("Content-Type"):
            test_headers = {**HEADERS, "Range": "bytes=0-1024"}
            res = SESSION.get(url, headers=test_headers, timeout=10, stream=True)

        content_type = res.headers.get("Content-Type", "").lower()
        if "video/" in content_type or "mpegurl" in content_type:
            return True
        if "octet-stream" in content_type and re.search(r"\.mp4(\?|$)", url, re.I):
            return True
        return False
    except Exception:
        return False


def process_scraped_channel(channel_info):
    name = channel_info["name"]
    page_url = channel_info["page_url"]
    stream_url = None

    try:
        response = SESSION.get(page_url, timeout=15)
        response.raise_for_status()
        stream_url = extract_stream_url(response.text)
    except Exception as e:
        print(f"  Erro ao processar '{name}': {e}")

    is_active = bool(stream_url) and validate_stream(stream_url)

    return {
        "name": name,
        "stream_url": stream_url,
        "logo": channel_info.get("logo", ""),
        "group": channel_info.get("group", "Filmes"),
        "page_url": page_url,
        "is_active": is_active,
    }


def process_existing_channel(name, info):
    stream_url = info.get("stream_url")
    is_active = bool(stream_url) and validate_stream(stream_url)

    return {
        "name": name,
        "stream_url": stream_url,
        "logo": info.get("logo", ""),
        "group": info.get("group", "Filmes"),
        "page_url": info.get("page_url", ""),
        "is_active": is_active,
    }


def generate_m3u8(state):
    lines = ["#EXTM3U"]

    channels_list = []
    for name, info in state.items():
        info_dict = info.copy()
        info_dict["name"] = name
        channels_list.append(info_dict)

    # Ordena por grupo e depois por nome
    sorted_channels = sorted(
        channels_list,
        key=lambda x: (x.get("group", "Filmes"), x.get("name", "")),
    )

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

    print(f"Sucesso! {PLAYLIST_FILE} gerado com {active_count} filmes.")


def main():
    print("Carregando estado anterior...")
    state = load_state()

    print("Coletando filmes do site...")
    scraped_channels = scrape_channels()
    print(f"Encontrados {len(scraped_channels)} filmes no site.")

    scraped_names = {ch["name"] for ch in scraped_channels}
    tasks = []

    for ch in scraped_channels:
        tasks.append(("scraped", ch))

    # Mantém canais antigos que sumiram do site (caso ainda estejam ativos)
    for name, info in state.items():
        if name not in scraped_names:
            tasks.append(("existing", {"name": name, "info": info}))

    print(f"Processando {len(tasks)} itens (extração de stream + validação)...")
    new_state = {}

    with ThreadPoolExecutor(max_workers=12) as executor:
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
            result = future.result()
            done += 1
            if done % 50 == 0 or done == len(tasks):
                print(f"  Progresso: {done}/{len(tasks)}")

            if result["is_active"] and result["stream_url"]:
                new_state[result["name"]] = {
                    "stream_url": result["stream_url"],
                    "logo": result["logo"],
                    "group": result["group"],
                    "page_url": result["page_url"],
                }

    print(f"Mantidos {len(new_state)} filmes com stream válido.")
    save_state(new_state)
    generate_m3u8(new_state)


if __name__ == "__main__":
    main()
