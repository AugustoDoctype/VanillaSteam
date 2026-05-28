import discord
import os
import aiohttp
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

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
    # Aumentamos o pageSize para 100 para ter mais opções na "peneira"
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
    print(f'✅ Sistema operando em alta performance como {bot.user.name}')

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

# --- TRATAMENTO DE ERRO (AVISO DE COOLDOWN) ---
@ofertas.error
async def ofertas_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Calma aí! O sistema está processando dados. Tente novamente em **{error.retry_after:.0f} segundos**.")

bot.run(TOKEN)