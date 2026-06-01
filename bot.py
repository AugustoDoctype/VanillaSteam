import discord
import os
import aiohttp
import logging
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, datetime

# ==========================================
# 1. CONFIGURAÇÕES INICIAIS E VARIÁVEIS
# ==========================================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

ID_CANAL_OFERTAS = 123456789012345678 
HORARIO_POSTAGEM = time(hour=10, minute=0)

# --- CONFIGURAÇÃO ISOLADA E PROFISSIONAL DE LOGS ---
formatador = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

file_handler = logging.FileHandler("vanilla.log", encoding="utf-8")
file_handler.setFormatter(formatador)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatador)

logger = logging.getLogger("Vanilla")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False 
# ---------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# 2. FUNÇÕES AUXILIARES (MOTOR DE BUSCA)
# ==========================================
async def buscar_promocoes_premium(session):
    """Busca o Top 10 de ofertas na CheapShark e valida o preço na Steam."""
    url_cheapshark = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&onSale=1&pageSize=100"
    
    try:
        async with session.get(url_cheapshark, timeout=10) as resposta:
            if resposta.status != 200: return []
            dados = await resposta.json()
    except Exception as e:
        logger.error(f"Erro na API CheapShark (Premium): {e}")
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
            
            if preco_usd_normal >= 14.99 and avaliacoes >= 5000 and desconto >= 50.0:
                url_steam = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
                
                async with session.get(url_steam) as resp_steam:
                    if resp_steam.status != 200: continue
                    dados_steam = await resp_steam.json()
                    
                    if dados_steam and dados_steam.get(app_id) and dados_steam[app_id]['success']:
                        info_preco = dados_steam[app_id]['data'].get('price_overview')
                        if info_preco:
                            preco_atual_brl = info_preco['final_formatted']
                            preco_original_brl = info_preco['initial_formatted']
                        else: continue
                    else: continue

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
                
                if len(jogos_filtrados) == 10: break
        except Exception:
            continue
            
    return jogos_filtrados


async def obter_cotacao_dolar(session):
    """Obtém a cotação atual do dólar comercial em tempo real."""
    url = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                dados = await resp.json()
                return float(dados["USDBRL"]["bid"])
    except Exception as e:
        logger.warning(f"Erro ao obter cotação do dólar, usando valor padrão. Erro: {e}")
    return 5.50 


async def buscar_promocoes_hype(session):
    """Busca o Top 5 de jogos extremamente populares (Grandes Franquias/AAA)."""
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Reviews&onSale=1&pageSize=40"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return []
            dados = await resp.json()
    except Exception as e: 
        logger.error(f"Erro na API CheapShark (Hype): {e}")
        return []

    jogos, adicionados = [], set()
    for j in dados:
        app_id = j['steamAppID']
        if app_id in adicionados or app_id == "0": continue
        
        if int(j.get('steamRatingCount', 0)) < 40000: continue

        url_steam = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
        async with session.get(url_steam) as resp_steam:
            if resp_steam.status == 200:
                ds = await resp_steam.json()
                if ds and ds.get(app_id) and ds[app_id]['success']:
                    info = ds[app_id]['data'].get('price_overview')
                    if info:
                        jogos.append({
                            'titulo': j['title'],
                            'preco_atual': info['final_formatted'],
                            'preco_original': info['initial_formatted'],
                            'desconto': f"{float(j['savings']):.0f}%",
                            'link': f"https://store.steampowered.com/app/{app_id}"
                        })
                        adicionados.add(app_id)
        if len(jogos) == 5: break
    return jogos


async def buscar_promocoes_indies(session):
    """Busca o Top 5 de Joias Escondidas (Preço baixo, nota gigante, estúdio menor)."""
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&onSale=1&pageSize=100"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return []
            dados = await resp.json()
    except Exception as e: 
        logger.error(f"Erro na API CheapShark (Indies): {e}")
        return []

    jogos, adicionados = [], set()
    for j in dados:
        app_id = j['steamAppID']
        if app_id in adicionados or app_id == "0": continue
        
        preco_base_usd = float(j['normalPrice'])
        votos_totais = int(j.get('steamRatingCount', 0))
        porcentagem_positiva = int(j.get('steamRatingPercent', 0))
        
        if preco_base_usd <= 20.0 and porcentagem_positiva >= 92 and 1000 <= votos_totais <= 25000:
            url_steam = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
            async with session.get(url_steam) as resp_steam:
                if resp_steam.status == 200:
                    ds = await resp_steam.json()
                    if ds and ds.get(app_id) and ds[app_id]['success']:
                        info = ds[app_id]['data'].get('price_overview')
                        if info:
                            jogos.append({
                                'titulo': j['title'],
                                'preco_atual': info['final_formatted'],
                                'preco_original': info['initial_formatted'],
                                'desconto': f"{float(j['savings']):.0f}%",
                                'nota': f"{porcentagem_positiva}%",
                                'link': f"https://store.steampowered.com/app/{app_id}"
                            })
                            adicionados.add(app_id)
        if len(jogos) == 5: break
    return jogos


# ==========================================
# 3. EVENTOS DO SISTEMA
# ==========================================
@bot.event
async def on_ready():
    logger.info(f"✅ Sistema operacional! Conectado como {bot.user.name}")
    
    if not jornal_da_manha.is_running():
        jornal_da_manha.start()
        logger.info("🕒 Automação diária agendada com sucesso.")


# ==========================================
# 4. TAREFAS AUTOMATIZADAS (EDIÇÃO PREMIUM)
# ==========================================
@tasks.loop(time=HORARIO_POSTAGEM)
async def jornal_da_manha():
    canal = bot.get_channel(ID_CANAL_OFERTAS)
    if not canal:
        logger.error("Erro na automação: ID do canal de ofertas inválido ou não encontrado.")
        return

    logger.info("Iniciando a grande varredura matinal para o jornal...")
    
    async with aiohttp.ClientSession() as session:
        lista_premium = await buscar_promocoes_premium(session)
        lista_hype = await buscar_promocoes_hype(session)
        lista_indies = await buscar_promocoes_indies(session)

    if lista_premium or lista_hype or lista_indies:
        data_hoje = datetime.now().strftime('%d/%m/%Y')
        
        embed_principal = discord.Embed(
            title=f"📰 VANILLA DAILY • Edição de {data_hoje}",
            description="Bom dia, gamers! O nosso motor de busca vasculhou os servidores e preparou o relatório econômico definitivo para hoje. Preparem as carteiras!",
            color=0x1b2838
        )
        
        if lista_premium:
            id_capa = lista_premium[0]['link'].split('/')[-1]
            embed_principal.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{id_capa}/header.jpg")

        embed_principal.add_field(name="🏆 AS MELHORES OPORTUNIDADES DA MANHÃ", value="---", inline=False)
        for i, jogo in enumerate(lista_premium[:5]):
            embed_principal.add_field(
                name=f"{i+1}️⃣ {jogo['titulo']}",
                value=f"📉 `{jogo['desconto_fmt']} OFF` | **{jogo['preco_atual']}** *(De: {jogo['preco_original']})*",
                inline=False
            )
            
        embed_principal.set_footer(text=f"Continua abaixo... • Gerado em {data_hoje}")
        await canal.send(embed=embed_principal)

        embed_suplemento = discord.Embed(
            title="🎯 SUPLEMENTO ESPECIAL: Categorias Destacadas",
            description="Dividimos os radares para quem procura os grandes blockbusters ou quer arriscar em novas obras-primas subestimadas.",
            color=0x2ecc71
        )

        if lista_hype:
            texto_hype = ""
            for jogo in lista_hype[:3]: 
                texto_hype += f"🔥 **{jogo['titulo']}** por `{jogo['preco_atual']}` ({jogo['desconto']} OFF)\n"
            embed_suplemento.add_field(name="🚀 Blockbusters de Peso", value=texto_hype or "Sem destaques", inline=False)

        if lista_indies:
            texto_indies = ""
            for jogo in lista_indies[:3]: 
                texto_indies += f"⭐ `{jogo['nota']}` **{jogo['titulo']}** por `{jogo['preco_atual']}`\n"
            embed_suplemento.add_field(name="💎 Joias Escondidas (Indies)", value=texto_indies or "Sem destaques", inline=False)

        embed_suplemento.set_footer(text="Vanilla Engine • Assinatura Diária Automática")
        await canal.send(embed=embed_suplemento)
        
        logger.info("Jornal de ofertas categorizado enviado com sucesso!")
    else:
        logger.warning("A varredura não encontrou jogos suficientes para montar a edição de hoje.")


# ==========================================
# 5. COMANDOS DO USUÁRIO (E COMPONENTES)
# ==========================================

class MenuOfertas(discord.ui.Select):
    def __init__(self, jogos):
        self.jogos = jogos
        opcoes = [
            discord.SelectOption(
                label=f"{i+1}. {jogo['titulo']}"[:100],
                description=f"De: {jogo['preco_original']} por {jogo['preco_atual']}",
                value=str(i),
                emoji="🎮"
            ) for i, jogo in enumerate(jogos)
        ]
        super().__init__(
            placeholder="Selecione um jogo para inspecionar...",
            min_values=1,
            max_values=1,
            options=opcoes
        )

    async def callback(self, interaction: discord.Interaction):
        index_jogo = int(self.values[0])
        jogo = self.jogos[index_jogo]
        steam_app_id = jogo['link'].split('/')[-1]
        
        embed_detalhes = discord.Embed(title=jogo['titulo'], color=0x1b2838)
        embed_detalhes.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_app_id}/header.jpg")
        
        alerta = "🚨 **DESCONTO HISTÓRICO!** " if jogo['desconto_raw'] >= 90 else ""
        embed_detalhes.description = (
            f"{alerta}\n"
            f"📉 **Desconto:** `{jogo['desconto_fmt']}`\n"
            f"💰 **Preço Atual:** {jogo['preco_atual']}\n"
            f"❌ **Preço Original:** ~~{jogo['preco_original']}~~\n"
            f"📊 **Popularidade:** `{jogo['popularidade']:,}` avaliações na Steam"
        )
        embed_detalhes.add_field(name="Link da Loja", value=f"[Adicionar à Biblioteca]({jogo['link']})")
        embed_detalhes.set_footer(text="Vanilla Engine • Use o menu novamente para ver outro jogo")

        await interaction.response.edit_message(embed=embed_detalhes, view=self.view)


class PainelOfertasView(discord.ui.View):
    def __init__(self, jogos):
        super().__init__(timeout=180)
        self.add_item(MenuOfertas(jogos))


@bot.command(name="ofertas")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def ofertas(ctx):
    """Retorna o Top 10 atual de ofertas da Steam com menu interativo."""
    logger.info(f"Comando !ofertas acionado por {ctx.author} (ID: {ctx.author.id})")
    feedback = await ctx.send("🔍 *Compilando o relatório econômico da Steam...*")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_premium(session)
    
    await feedback.delete()

    if not jogos:
        await ctx.send("❌ O radar não detectou nenhuma oferta nível AAA no momento.")
        return

    embed_lista = discord.Embed(
        title="🎮 Top 10 Ofertas Premium", 
        description="Escolha qualquer jogo no menu abaixo para ver fotos, descontos e detalhes adicionais!",
        color=0x1b2838
    )
    
    emojis_rank = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, jogo in enumerate(jogos):
        embed_lista.add_field(
            name=f"{emojis_rank[i]} {jogo['titulo']}", 
            value=f"`{jogo['desconto_fmt']} OFF` -> **{jogo['preco_atual']}**", 
            inline=True
        )

    view_interativa = PainelOfertasView(jogos)
    await ctx.send(embed=embed_lista, view=view_interativa)


# Mapeamento focado no público Brasileiro (Lojas conhecidas e confiáveis)
LOJAS_CHEAPSHARK = {
    "1": "Steam",
    "3": "Green Man Gaming", 
    "7": "GOG",              
    "25": "Epic Games"       
}

@bot.command(name="buscar")
async def buscar(ctx, *, nome_jogo: str):
    """Busca o preço de um jogo e compara nas principais lojas (Steam, Epic, GOG, etc)."""
    logger.info(f"Usuário {ctx.author} buscou pelo jogo: '{nome_jogo}'")
    msg_espera = await ctx.send(f"🔎 Consultando os servidores, histórico e lojas concorrentes para **{nome_jogo}**...")

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Busca básica para pegar o ID
            url_busca = f"https://www.cheapshark.com/api/1.0/games?title={nome_jogo.replace(' ', '%20')}&limit=1"
            async with session.get(url_busca) as resp:
                dados_busca = await resp.json()

            if not dados_busca:
                await msg_espera.edit(content=f"❌ Não encontrei nenhum jogo com o nome '{nome_jogo}'.")
                return

            game_id = dados_busca[0].get('gameID')
            steam_app_id = dados_busca[0].get('steamAppID')
            titulo_oficial = dados_busca[0].get('external')
            preco_atual_usd = float(dados_busca[0].get('cheapest', 0))

            if not steam_app_id or steam_app_id == "0":
                await msg_espera.edit(content=f"ℹ️ **{titulo_oficial}** não está disponível na Steam/banco de dados principal.")
                return

            # 2. Busca avançada (Histórico + Outras Lojas)
            url_historico = f"https://www.cheapshark.com/api/1.0/games?id={game_id}"
            async with session.get(url_historico) as resp_hist:
                dados_hist = await resp_hist.json()
            
            cotacao_hoje = await obter_cotacao_dolar(session)
            
            # Cálculo de histórico
            info_historico = dados_hist.get('cheapestPriceEver', {})
            menor_preco_usd = float(info_historico.get('price', 0))
            timestamp_menor = info_historico.get('date', 0)
            menor_preco_brl = menor_preco_usd * cotacao_hoje
            data_menor = datetime.fromtimestamp(timestamp_menor).strftime('%d/%m/%Y') if timestamp_menor else "Desconhecida"

            # 3. Comparador de Lojas (Agrupa apenas as strings para usar depois)
            deals = dados_hist.get('deals', [])
            texto_outras_lojas = ""
            
            for deal in deals:
                store_id = deal.get('storeID')
                if store_id in LOJAS_CHEAPSHARK and store_id != "1":
                    preco_usd_loja = float(deal.get('price', 0))
                    deal_id = deal.get('dealID')
                    link_loja = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
                    
                    texto_outras_lojas += f"🏪 **{LOJAS_CHEAPSHARK[store_id]}**: US$ {preco_usd_loja:.2f} (Preço Americano) - [Comprar]({link_loja})\n"
                    
            # 4. Dados da Steam Brasil (Criação do Embed)
            url_steam = f"https://store.steampowered.com/api/appdetails?appids={steam_app_id}&cc=br&filters=price_overview"
            async with session.get(url_steam) as resp_steam:
                dados_steam = await resp_steam.json()
                
                if not dados_steam or not dados_steam.get(steam_app_id) or not dados_steam[steam_app_id]['success']:
                    await msg_espera.edit(content=f"❌ Sem dados de preço para **{titulo_oficial}** na Steam Brasil.")
                    return

                info_preco = dados_steam[steam_app_id]['data'].get('price_overview')
                
                # AQUI: O Embed é criado no momento correto
                embed = discord.Embed(title=titulo_oficial, color=0x1b2838)
                embed.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_app_id}/header.jpg")

                if info_preco:
                    p_atual = info_preco['final_formatted']
                    p_orig = info_preco['initial_formatted']
                    desc = info_preco.get('discount_percent', 0)
                    
                    if desc > 0:
                        embed.description = f"🔥 **Promoção Ativa na Steam!**\n💰 De: ~~{p_orig}~~ por **{p_atual}**\n📉 Desconto: **{desc}%**\n"
                    else:
                        embed.description = f"💰 Preço na Steam: **{p_atual}**\n*Este jogo não está em oferta na Steam no momento.*\n"
                    
                    embed.description += "\n📊 **Análise de Oportunidade:**\n"
                    
                    if preco_atual_usd <= menor_preco_usd:
                        embed.description += f"🏆 **PREÇO HISTÓRICO!** Recorde alcançado (Est. **R$ {menor_preco_brl:.2f}**)."
                    else:
                        diferenca = ((preco_atual_usd - menor_preco_usd) / menor_preco_usd) * 100
                        embed.description += (
                            f"📉 Menor preço histórico estimado: **R$ {menor_preco_brl:.2f}** *(em {data_menor})*.\n"
                            f"ℹ️ O menor preço atual está **{diferenca:.0f}% acima** do recorde."
                        )
                else:
                    embed.description = "ℹ️ Jogo gratuito ou sem preço listado na loja."

                # AQUI: Inserimos as lojas alternativas que agrupamos no Passo 3
                if texto_outras_lojas:
                    embed.add_field(name="🌍 Lojas Alternativas (Referência Global)", value=texto_outras_lojas, inline=False)

                embed.add_field(name="Link na Steam", value=f"[Abrir Página da Steam](https://store.steampowered.com/app/{steam_app_id})", inline=False)
                embed.set_footer(text="Vanilla Engine • Valores de outras lojas estão em Dólar, pois não incluem o preço localizado BR.")
                
                await msg_espera.delete()
                await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Erro crítico na busca do jogo '{nome_jogo}': {e}", exc_info=True)
        await msg_espera.edit(content="⚠️ Ocorreu um erro interno ao processar a análise e as lojas.")


@bot.command(name="hype")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def hype(ctx):
    """Lista os maiores blockbusters do mercado que estão em promoção."""
    logger.info(f"Comando !hype acionado por {ctx.author}")
    feedback = await ctx.send("🚀 *Rastreando os maiores blockbusters da indústria...*")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_hype(session)
        
    await feedback.delete()
    if not jogos:
        await ctx.send("❌ Nenhum titã dos games preencheu os critérios de oferta hoje.")
        return

    embed = discord.Embed(
        title="🚀 Radar de Heavy Hype: Os Gigantes em Oferta",
        description="Jogos aclamados, com comunidades gigantescas e preços reduzidos.",
        color=0xe91e63
    )
    for i, j in enumerate(jogos):
        embed.add_field(
            name=f"{i+1}️⃣ {j['titulo']}",
            value=f"💰 **{j['preco_atual']}** (~~{j['preco_original']}~~) | 📉 `{j['desconto']} OFF`\n🔗 [Ir para a Steam]({j['link']})",
            inline=False
        )
    embed.set_footer(text="Vanilla Engine")
    await ctx.send(embed=embed)


@bot.command(name="indies")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def indies(ctx):
    """Lista joias escondidas do cenário indie altamente aclamadas."""
    logger.info(f"Comando !indies acionado por {ctx.author}")
    feedback = await ctx.send("💎 *Garimpando joias escondidas no cenário indie...*")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_indies(session)
        
    await feedback.delete()
    if not jogos:
        await ctx.send("❌ O garimpo não encontrou nenhuma joia rara nas últimas horas.")
        return

    embed = discord.Embed(
        title="💎 Joias Escondidas do Mercado",
        description="Pequenos estúdios, preços baixos e aprovação quase perfeita pela crítica!",
        color=0x2ecc71
    )
    for i, j in enumerate(jogos):
        embed.add_field(
            name=f"{i+1}️⃣ {j['titulo']}",
            value=f"⭐ Aprovação: `{j['nota']}`\n💰 **{j['preco_atual']}** (~~{j['preco_original']}~~) | 📉 `{j['desconto']} OFF`\n🔗 [Ir para a Steam]({j['link']})",
            inline=False
        )
    embed.set_footer(text="Vanilla Engine")
    await ctx.send(embed=embed)


# ==========================================
# 6. INICIALIZAÇÃO DO BOT
# ==========================================
if __name__ == "__main__":
    bot.run(TOKEN)