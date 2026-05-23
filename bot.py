import discord
import os
import requests
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime # NOVA DEPENDÊNCIA (NATIVA)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FUNÇÕES DE SUPORTE (MANTIDAS) ---
def obter_cotacao_dolar():
    try:
        url = "https://economia.awesomeapi.com.br/last/USD-BRL"
        resposta = requests.get(url, timeout=5)
        resposta.raise_for_status()
        dados = resposta.json()
        return float(dados['USDBRL']['bid'])
    except Exception as e:
        print(f"Erro cotação: {e}")
        return 5.30 # Valor de segurança um pouco mais alto

def buscar_promocoes_premium(cotacao):
    # O SEGREDO ESTÁ AQUI:
    # 1. metacritic=80 -> A API já elimina o lixo.
    # 2. sortBy=Deal Rating -> Usa o algoritmo da própria API que cruza Nota + Desconto + Preço.
    # 3. onSale=1 -> Garante que o jogo está em promoção.
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&metacritic=80&onSale=1"
    
    try:
        resposta = requests.get(url, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.RequestException as e:
        print(f"Erro na API CheapShark: {e}")
        return []

    jogos_filtrados = []
    jogos_adicionados = set() # Controle para evitar jogos duplicados (Ex: Edição Normal vs Deluxe)
    
    for jogo in dados:
        try:
            preco_usd = float(jogo['normalPrice'])
            desconto = float(jogo['savings'])
            metacritic = int(jogo['metacriticScore'])
            app_id = jogo['steamAppID']
            
            # Como a API já filtrou a nota, nosso filtro local fica focado no preço e agressividade do desconto
            if preco_usd >= 19.99 and desconto >= 50.0:
                
                # Evita colocar o mesmo jogo duas vezes na lista
                if app_id in jogos_adicionados:
                    continue
                    
                preco_atual_brl = float(jogo['salePrice']) * cotacao
                preco_original_brl = preco_usd * cotacao
                imagem_hd = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"

                jogos_filtrados.append({
                    'titulo': jogo['title'],
                    'preco_atual_raw': preco_atual_brl,
                    'preco_atual_fmt': f"R$ {preco_atual_brl:.2f}".replace('.', ','),
                    'preco_original_fmt': f"R$ {preco_original_brl:.2f}".replace('.', ','),
                    'desconto_raw': desconto,
                    'desconto_fmt': f"{desconto:.0f}%",
                    'nota': metacritic,
                    'imagem': imagem_hd,
                    'link': f"https://store.steampowered.com/app/{app_id}"
                })
                
                jogos_adicionados.add(app_id)
                
                # Para assim que encontrar os 5 melhores
                if len(jogos_filtrados) == 5:
                    break
                    
        except (ValueError, KeyError, TypeError):
            continue
            
    return jogos_filtrados

    for jogo in dados:
        try:
            # Mantendo os critérios rigorosos de qualidade
            preco_usd = float(jogo['normalPrice'])
            desconto = float(jogo['savings'])
            metacritic = int(jogo['metacriticScore'])
            app_id = jogo['steamAppID']
            
            if preco_usd >= 19.99 and desconto >= 50.0 and metacritic >= 80:
                preco_atual_brl = float(jogo['salePrice']) * cotacao
                preco_original_brl = preco_usd * cotacao
                imagem_hd = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"

                jogos_filtrados.append({
                    'titulo': jogo['title'],
                    'preco_atual_raw': preco_atual_brl,
                    'preco_atual_fmt': f"R$ {preco_atual_brl:.2f}".replace('.', ','),
                    'preco_original_fmt': f"R$ {preco_original_brl:.2f}".replace('.', ','),
                    'desconto_raw': desconto,
                    'desconto_fmt': f"{desconto:.0f}%",
                    'nota': metacritic,
                    'imagem': imagem_hd,
                    'link': f"https://store.steampowered.com/app/{app_id}"
                })
        except (ValueError, KeyError, TypeError):
            continue
            
    return jogos_filtrados[:5] # Top 5 melhores descontos que passaram no filtro

# --- COMANDO DO DISCORD ATUALIZADO (MAIS CHAMATIVO) ---
@bot.event
async def on_ready():
    print(f'✅ Vitrine Premium de {bot.user.name} online!')

@bot.command(name="ofertas")
async def ofertas(ctx):
    # Feedback inicial mais limpo
    feedback = await ctx.send("<a:loading:123456789012345678> *Consultando especialistas e cotações...*") # Use um ID de emoji animado se tiver
    
    cotacao_atual = obter_cotacao_dolar()
    jogos = buscar_promocoes_premium(cotacao_atual)
    
    await feedback.delete() # Apaga o feedback inicial

    if not jogos:
        await ctx.send("❌ Não encontramos ofertas 'nível A' na Steam hoje.")
        return

    for jogo in jogos:
        # TÉCNICA 1: COR DINÂMICA
        # Define a cor baseada na agressividade do desconto
        cor_embed = discord.Color.dark_gray() # Padrão
        emoji_titulo = "🎮"

        if jogo['desconto_raw'] >= 75:
            cor_embed = discord.Color.red() # SUPER DESCONTO
            emoji_titulo = "🚨"
        elif jogo['desconto_raw'] >= 60:
            cor_embed = discord.Color.gold() # ÓTIMO NEGÓCIO
            emoji_titulo = "💎"

        # Criação do Embed
        embed = discord.Embed(
            # TÉCNICA 2: EMOJI NO TÍTULO
            title=f"{emoji_titulo} {jogo['titulo']}",
            url=jogo['link'],
            color=cor_embed
        )
        
        # TÉCNICA 3: MARKDOWN AVANÇADO NA DESCRIÇÃO
        embed.description = (
            f"**Nota Metacritic:** ⭐ `{jogo['nota']}/100`\n\n"
            f"💰 **OFERTA IMPERDÍVEL:**\n"
            f"De: ~~{jogo['preco_original_fmt']}~~\n"
            f"Por apenas: 🎉 **{jogo['preco_atual_fmt']}**\n"
            f"*(Você economiza {jogo['desconto_fmt']})*"
        )
        
        # Imagem HD de destaque (Já tínhamos acertado)
        embed.set_image(url=jogo['imagem']) 
        
        # TÉCNICA 4: RODAPÉ COM TIMESTAMP
        horario = datetime.now().strftime("%H:%M")
        embed.set_footer(text=f"Via Steam • Verificado às {horario}", icon_url="https://store.steampowered.com/favicon.ico")
        
        await ctx.send(embed=embed)

bot.run(TOKEN)
