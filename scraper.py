import os
import json
import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://comandoplay.tv/category/movies-2/"
STATE_FILE = "channels.json"
PLAYLIST_FILE = "playlist.m3u8"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def scrape_channels():
    channels = []
    page = 1
    while True:
        print(f"Coletando página {page}...")
        url = f"{BASE_URL}?pagina={page}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print(f"Erro ao buscar página {page}: {e}")
            break
            
        soup = BeautifulSoup(response.text, 'html.parser')
        page_channels = []
        
        for li in soup.find_all('li'):
            a = li.find('a', class_='cc')
            if not a:
                continue
            
            href = a.get('href')
            if not href:
                continue
            
            full_url = href if href.startswith('http') else f"https://comandoplay.tv{href}"
            
            name_tag = a.find('b')
            name = name_tag.get_text(strip=True) if name_tag else "Canal Desconhecido"
            
            logo_tag = a.find('img')
            logo = logo_tag.get('src') if logo_tag else ""
            
            tg = a.find('span', class_='tg')
            categories = [span.get_text(strip=True) for span in tg.find_all('span')] if tg else []
            group = categories[0] if categories else "Geral"
            
            page_channels.append({
                "name": name,
                "page_url": full_url,
                "logo": logo,
                "group": group
            })
        
        if not page_channels:
            print("Nenhum canal encontrado. Finalizando paginação.")
            break
            
        channels.extend(page_channels)
        page += 1
        
    return channels

def process_scraped_channel(channel_info):
    name = channel_info["name"]
    page_url = channel_info["page_url"]
    
    stream_url = None
    try:
        response = requests.get(page_url, headers=HEADERS, timeout=10)
        html = response.text
        m3u8_urls = re.findall(r'(https?://[^\s\'"]+\.m3u8[^\s\'"]*)', html)
        if m3u8_urls:
            stream_url = m3u8_urls[0]
    except Exception:
        pass
    
    is_active = False
    if stream_url:
        try:
            test_headers = {**HEADERS, "Range": "bytes=0-1024"}
            response = requests.get(stream_url, headers=test_headers, timeout=5)
            if response.status_code in [200, 206]:
                is_active = True
        except Exception:
            pass
            
    return {
        "name": name,
        "stream_url": stream_url,
        "logo": channel_info["logo"],
        "group": channel_info["group"],
        "page_url": page_url,
        "is_active": is_active
    }

def process_existing_channel(name, info):
    stream_url = info.get("stream_url")
    is_active = False
    if stream_url:
        try:
            test_headers = {**HEADERS, "Range": "bytes=0-1024"}
            response = requests.get(stream_url, headers=test_headers, timeout=5)
            if response.status_code in [200, 206]:
                is_active = True
        except Exception:
            pass
    return {
        "name": name,
        "stream_url": stream_url,
        "logo": info.get("logo", ""),
        "group": info.get("group", "Geral"),
        "page_url": info.get("page_url", ""),
        "is_active": is_active
    }

def generate_m3u8(state):
    lines = ["#EXTM3U"]
    
    # CORREÇÃO: Reconstrói a lista garantindo que a chave "name" exista dentro do dicionário
    channels_list = []
    for name, info in state.items():
        info_dict = info.copy()
        info_dict["name"] = name
        channels_list.append(info_dict)
        
    # Ordena por grupo e depois por nome, usando .get() como proteção extra
    sorted_channels = sorted(channels_list, key=lambda x: (x.get("group", "Geral"), x.get("name", "")))
    
    active_count = 0
    for ch in sorted_channels:
        if not ch.get("stream_url"):
            continue
            
        logo = ch.get("logo", "")
        group = ch.get("group", "Geral").replace('"', '\\"')
        name = ch["name"].replace('"', '\\"')
        url = ch["stream_url"]
        
        extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}'
        lines.append(extinf)
        lines.append(url)
        active_count += 1
        
    with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"Sucesso! {PLAYLIST_FILE} gerado com {active_count} canais ativos.")

def main():
    print("Carregando estado anterior...")
    state = load_state()
    
    print("Coletando canais do site...")
    scraped_channels = scrape_channels()
    print(f"Encontrados {len(scraped_channels)} canais no site.")
    
    scraped_names = {ch["name"] for ch in scraped_channels}
    tasks = []
    
    for ch in scraped_channels:
        tasks.append(("scraped", ch))
        
    for name, info in state.items():
        if name not in scraped_names:
            tasks.append(("existing", {"name": name, "info": info}))
            
    print(f"Testando a atividade de {len(tasks)} canais...")
    
    new_state = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_task = {}
        for task in tasks:
            if task[0] == "scraped":
                future = executor.submit(process_scraped_channel, task[1])
            else:
                future = executor.submit(process_existing_channel, task[1]["name"], task[1]["info"])
            future_to_task[future] = task
            
        for future in as_completed(future_to_task):
            result = future.result()
            if result["is_active"] and result["stream_url"]:
                new_state[result["name"]] = {
                    "stream_url": result["stream_url"],
                    "logo": result["logo"],
                    "group": result["group"],
                    "page_url": result["page_url"]
                }
                
    print(f"Mantidos {len(new_state)} canais ativos.")
    save_state(new_state)
    generate_m3u8(new_state)

if __name__ == "__main__":
    main()