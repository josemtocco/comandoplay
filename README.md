# Lista M3U Automatizada – Filmes (Comando Play)

Este repositório gera e mantém automaticamente uma lista de reprodução M3U com **todos os filmes** do site [comandoplay.tv](https://comandoplay.tv/category/movies-2/), otimizada para uso em players IPTV (SS IPTV, TiviMate, VLC, etc.).

## 🔄 Como funciona

1. **Coleta completa**: O script percorre **todas as páginas** da categoria de filmes (`/category/movies-2/page/N/`).
2. **Extração de links**: Em cada página de filme, localiza os hosters disponíveis (EmbedPlay, Mixdrop, Morencius, Doodstream, etc.), priorizando o servidor marcado como **PRINCIPAL**.
3. **Inteligência de estado**:
   - ✅ **Acrescenta** novos filmes encontrados.
   - ✅ **Mantém** filmes que continuam com link válido.
   - ❌ **Remove** automaticamente entradas que perderam o stream.
4. **Categorização**: Usa a qualidade (WEB-DL, CAMRip, etc.) como `group-title`.

## ⏱️ Atualização

A lista é atualizada automaticamente **a cada 6 horas** pelo GitHub Actions.

## 📺 Como usar no SS IPTV

1. Abra o aplicativo SS IPTV.
2. Vá em **Configurações** > **Geral** > **Obter Lista**.
3. Adicione um novo item:
   - **Nome**: `Filmes ComandoPlay (Auto)`
   - **URL**: `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPOSITORIO/main/playlist.m3u8`
4. Salve e recarregue a lista.

## ⚠️ Observações

- Os streams vêm de hosters externos (Mixdrop, EmbedPlay…). Alguns players lidam melhor que outros com esses links.
- O script é respeitoso com o site (pequenas pausas entre páginas e concorrência controlada).
- Rode localmente com: `pip install -r requirements.txt && python scraper.py`
