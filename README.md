#Lista M3U — ComandoPlay.tv (otimizado para SS IPTV)
======================================================

Gera playlist M3U com filmes do [ComandoPlay.tv](https://comandoplay.tv/),
priorizando links que o **SS IPTV** consegue tocar.

## Por que os links anteriores não tocavam?

1. Eram páginas de player (`/watch?v=...`), não streams.
2. O HLS do brstream tem **áudio separado** do vídeo — SS IPTV costuma
   tocar só a imagem ou falhar.
3. Solução: extrair **MP4 progressivo do Mixdrop** (vídeo+áudio juntos).

## Ordem de preferência dos links

| Prioridade | Fonte     | Formato | SS IPTV      |
|-----------|-----------|---------|--------------|
| 1         | Mixdrop   | MP4     | Melhor       |
| 2         | brstream  | HLS     | Pode sem som |
| 3         | outros    | varia   | Incerto      |

## Uso

```bash
pip install -r requirements.txt

# Windows
rodar_no_brasil.bat
rodar_no_brasil.bat --pages 3

# Linux/macOS
./rodar_no_brasil.sh
./rodar_no_brasil.sh --pages 3
./rodar_no_brasil.sh --prefer hls   # se quiser HLS em vez de MP4
```

Saída: `playlists/comandoplay.m3u`

### Testar um link

```bash
node resolve_stream.js "https://embedplay.icu/player.php?id=XXXX"
```

## Dicas para SS IPTV

- Use a lista **logo após gerar** (URLs do Mixdrop têm assinatura com prazo).
- No SS IPTV: adicione a lista como **fonte M3U** (URL ou arquivo).
- Se um título não abrir, gere de novo ou abra a página no site e use outro servidor.
- Regenerar a lista com frequência (GitHub Actions a cada 12h ou rode o script).

## Stack

- Python 3 + asyncio + aiohttp (scraping paralelo)
- Node.js helper (`resolve_stream.js`) — unpack do packer Mixdrop + HLS
- Extração do objeto `video` do JW Player (brstream)

## Aviso

Conteúdos e hosts são de terceiros. Use conforme as leis do seu país.
