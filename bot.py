import discord
import os
import aiohttp
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands, tasks # tasks
from datetime import time, datetime



load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FUNÇÕES ASSÍNCRONAS DE BUSCA ---
async def obter_cotacao_dolar(session):
    url = "https://economia.awesomeapi.com.br/last/USD-BRL"
    try:
        async with session.get(url, timeout=5) as resposta:
            if resposta.status == 200:
                dados = await resposta.json()
                return float(dados['USDBRL']['bid'])
    except Exception as e:
        print(f"Erro na cotação: {e}")
    return 5.30

async def buscar_promocoes_premium(session, cotacao):
    # Aumentar o pageSize para 100 para ter mais opções na "peneira"
    url_cheapshark = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&onSale=1&pageSize=100"
    
    try:
        async with session.get(url_cheapshark, timeout=10) as resposta:
            if resposta.status != 200: return []
            dados = await resposta.json()
    except:
        return []

    jogos_filtrados = []
    jogos_adicionados = set()
    
    for jogo in dados:
        try:
            app_id = jogo['steamAppID']
            if app_id in jogos_adicionados: continue
            
            preco_usd_normal = float(jogo['normalPrice'])
            desconto = float(jogo['savings'])
            avaliacoes = int(jogo.get('steamRatingCount', 0))
            
            # FILTROS EQUILIBRADOS:
            # - Preço original >= $14.99 (Pega jogos médios e grandes)
            # - Avaliações >= 5.000 (Garante que o jogo é conhecido)
            # - Desconto >= 50% (Foco em promoção real)
            if preco_usd_normal >= 14.99 and avaliacoes >= 5000 and desconto >= 50.0:
                
                # Consulta de Preço Regional na Steam (Precisão 100%)
                url_steam = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
                
                async with session.get(url_steam) as resp_steam:
                    if resp_steam.status != 200: continue
                    dados_steam = await resp_steam.json()
                    
                    if dados_steam and dados_steam.get(app_id) and dados_steam[app_id]['success']:
                        info_preco = dados_steam[app_id]['data'].get('price_overview')
                        
                        if info_preco:
                            preco_atual_brl = info_preco['final_formatted']
                            preco_original_brl = info_preco['initial_formatted']
                        else:
                            continue
                    else:
                        continue

                jogos_filtrados.append({
                    'titulo': jogo['title'],
                    'preco_atual': preco_atual_brl,
                    'preco_original': preco_original_brl,
                    'desconto_raw': desconto,
                    'desconto_fmt': f"{desconto:.0f}%",
                    'popularidade': avaliacoes,
                    'link': f"https://store.steampowered.com/app/{app_id}"
                })
                
                jogos_adicionados.add(app_id)
                
                # Agora o limite de 10 será atingido mais facilmente
                if len(jogos_filtrados) == 10:
                    break
        except:
            continue

    return jogos_filtrados

# --- EVENTOS DO BOT ---
@bot.event
async def on_ready():
    print(f'✅ Sistema operando como {bot.user.name}')
    
    # Inicia a automação se ela não estiver rodando
    if not jornal_da_manha.is_running():
        jornal_da_manha.start()
        print("🕒 Automação diária agendada com sucesso.")

# --- COMANDO PRINCIPAL COM COOLDOWN ---
@bot.command(name="ofertas")
@commands.cooldown(1, 60, commands.BucketType.guild) # 1 uso por minuto por servidor
async def ofertas(ctx):
    feedback = await ctx.send("🔍 *Processando dados de mercado e filtrando catálogo da Steam...*")
    
    async with aiohttp.ClientSession() as session:
        cotacao_atual = await obter_cotacao_dolar(session)
        jogos = await buscar_promocoes_premium(session, cotacao_atual)
    
    await feedback.delete()

    if not jogos:
        await ctx.send("❌ O radar não detectou nenhuma oferta nível AAA no momento.")
        return

    embed = discord.Embed(
        title="🔥 Top 10 Ofertas Premium (Steam)",
        description="Apenas jogos de alto calibre com descontos agressivos aprovados pelo nosso filtro.",
        color=0x1b2838 
    )
    
    # Emojis do Pódio
    emojis_rank = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, jogo in enumerate(jogos):
        # Selo de Pechincha para descontos extremos
        alerta_pechincha = "🚨 **HISTÓRICO!** " if jogo['desconto_raw'] >= 90 else ""
        
        info_jogo = (
            f"💰 {alerta_pechincha}De: ~~{jogo['preco_original']}~~ ➔ **{jogo['preco_atual']}**\n"
            f"📉 Economia: `{jogo['desconto_fmt']}` | 👥 Pop: `{jogo['popularidade']:,}` avaliações\n"
            f"🔗 [Acessar a Oferta]({jogo['link']})"
        )
        
        embed.add_field(
            name=f"{emojis_rank[i]} {jogo['titulo']}",
            value=info_jogo,
            inline=False 
        )
    
    embed.set_footer(
        text=f"Cotação base: R$ {cotacao_atual:.2f} • {datetime.now().strftime('%H:%M')}", 
        icon_url="https://store.steampowered.com/favicon.ico"
    )
    
    await ctx.send(embed=embed)

# -- BUSCAR JOGO ---
@bot.command(name="buscar")
async def buscar(ctx, *, nome_jogo: str):
    """Busca o preço de um jogo específico na Steam."""
    msg_espera = await ctx.send(f"🔎 Procurando por **{nome_jogo}**...")

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Busca no CheapShark para pegar o Steam ID
            url_busca = f"https://www.cheapshark.com/api/1.0/games?title={nome_jogo.replace(' ', '%20')}&limit=1"
            async with session.get(url_busca) as resp:
                dados_busca = await resp.json()

            if not dados_busca:
                await msg_espera.edit(content=f"❌ Não encontrei nenhum jogo com o nome '{nome_jogo}'.")
                return

            steam_app_id = dados_busca[0].get('steamAppID')
            titulo_oficial = dados_busca[0].get('external')

            # Se o jogo não tiver um ID da Steam (ex: jogo exclusivo da Epic ou GOG)
            if not steam_app_id or steam_app_id == "0":
                await msg_espera.edit(content=f"ℹ️ Encontrei **{titulo_oficial}**, mas ele não parece estar disponível na Steam.")
                return

            # 2. Busca o preço oficial na Steam (cc=br para vir em Reais)
            url_steam = f"https://store.steampowered.com/api/appdetails?appids={steam_app_id}&cc=br&filters=price_overview"
            
            async with session.get(url_steam) as resp_steam:
                dados_steam = await resp_steam.json()
                
                if not dados_steam or not dados_steam.get(steam_app_id) or not dados_steam[steam_app_id]['success']:
                    await msg_espera.edit(content=f"❌ Não consegui obter os preços de **{titulo_oficial}** na Steam Brasil.")
                    return

                # Extrai dados de preço
                data = dados_steam[steam_app_id].get('data', {})
                info_preco = data.get('price_overview')

                embed = discord.Embed(title=titulo_oficial, color=0x1b2838)
                
                # URL Oficial da Steam para imagens (mais confiável)
                img_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_app_id}/header.jpg"
                embed.set_image(url=img_url)

                if info_preco:
                    preco_atual = info_preco['final_formatted']
                    preco_original = info_preco['initial_formatted']
                    desconto = info_preco.get('discount_percent', 0)

                    if desconto > 0:
                        embed.description = f"🔥 **Promoção ativa!**\n💰 De: ~~{preco_original}~~ por **{preco_atual}**\n📉 Desconto de **{desconto}%**"
                    else:
                        embed.description = f"💰 Preço atual: **{preco_atual}**\n\n*Este jogo não está em oferta no momento.*"
                else:
                    embed.description = "ℹ️ Este jogo parece ser gratuito ou não possui preço definido na loja."

                embed.add_field(name="Link na Loja", value=f"[Página do Jogo na Steam](https://store.steampowered.com/app/{steam_app_id})", inline=False)
                
                await msg_espera.delete()
                await ctx.send(embed=embed)

    except Exception as e:
        print(f"ERRO NO COMANDO BUSCAR: {e}") # Isso vai aparecer no seu terminal do VS Code
        await msg_espera.edit(content="⚠️ Ocorreu um erro interno ao processar a busca. Verifique o console.")

# --- TRATAMENTO DE ERRO (AVISO DE COOLDOWN) ---
@ofertas.error
async def ofertas_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Calma aí! O sistema está processando dados. Tente novamente em **{error.retry_after:.0f} segundos**.")

# --- CONFIGURAÇÃO DA AUTOMAÇÃO ---
HORARIO_POSTAGEM = time(hour=10, minute=0) # Definido para as 10:00 da manhã
ID_CANAL_OFERTAS = 1507542658359230496 # ID DO CANAL

@tasks.loop(seconds=10)
async def jornal_da_manha():
    canal = bot.get_channel(ID_CANAL_OFERTAS)
    if not canal:
        print("❌ Erro: Não consegui encontrar o canal de ofertas.")
        return

    print(f"⏰ {datetime.now().strftime('%H:%M')} - Iniciando postagem automática...")
    
    # Reutilizamos a lógica de busca (idealmente você moveria a busca para uma função separada)
    async with aiohttp.ClientSession() as session:
        cotacao = await obter_cotacao_dolar(session)
        jogos = await buscar_promocoes_premium(session, cotacao)

    if jogos:
        embed = discord.Embed(
            title="🗞️ Jornal NemoSteam: As Melhores de Hoje",
            description="Bom dia! Aqui estão as ofertas mais quentes que acabaram de sair do forno.",
            color=0x1b2838
        )
        
        emojis_rank = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, jogo in enumerate(jogos):
            embed.add_field(
                name=f"{emojis_rank[i]} {jogo['titulo']}",
                value=f"💰 **{jogo['preco_atual']}** (~~{jogo['preco_original']}~~)\n🔗 [Ver na Steam]({jogo['link']})",
                inline=False
            )
        
        await canal.send(embed=embed)

bot.run(TOKEN)