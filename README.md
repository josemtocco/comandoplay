# Lista M3U Automatizada para SS IPTV

Este repositório gera e mantém automaticamente uma lista de reprodução M3U de canais de TV do Brasil, otimizada para uso no **SS IPTV**.

## 🔄 Como funciona
1. **Coleta**: O script navega por todas as páginas do site fonte, simulando o "Carregar Mais".
2. **Validação**: Cada canal tem seu link `.m3u8` testado em tempo real para garantir que está ativo.
3. **Inteligência**: 
   - ✅ **Acrescenta** novos canais encontrados.
   - ✅ **Mantém** canais que continuam ativos.
   - ❌ **Remove** automaticamente canais inativos.
4. **Categorização**: Os canais são agrupados exatamente como no site de origem.

## ⏱️ Atualização
A lista é atualizada automaticamente **a cada 6 horas** pelo GitHub Actions.

## 📺 Como usar no SS IPTV
1. Abra o aplicativo SS IPTV.
2. Vá em **Configurações** > **Geral** > **Obter Lista**.
3. Adicione um novo item:
   - **Nome**: `TV Brasil (Auto)`
   - **URL**: `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPOSITORIO/main/playlist.m3u8`
4. Salve e recarregue a lista.
