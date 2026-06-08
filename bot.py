import discord
import os
import aiohttp
import logging
from logging.handlers import RotatingFileHandler
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, datetime, timezone, timedelta

# ==========================================
# 1. CONFIGURAÇÕES INICIAIS E DESIGN
# ==========================================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
ID_CANAL_OFERTAS = 1440018888573194514 

# --- DESIGN PADRONIZADO (CORES E ICONES) ---
COR_PRINCIPAL = 0x1b2838  # Azul Steam (Vanilla Padrão)
COR_SUCESSO = 0x2ecc71    # Verde para Indies e Suplementos
COR_HYPE = 0xe91e63       # Rosa/Vermelho para Blockbusters

EMOJIS_RANK = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
LOJAS_CHEAPSHARK = {"1": "Steam", "3": "Green Man Gaming", "7": "GOG", "25": "Epic Games"}

# --- CONFIGURAÇÃO DE HORÁRIOS BRASÍLIA (UTC-3) ---
fuso_brasilia = timezone(timedelta(hours=-3))
HORARIOS_JORNAL = [
    time(hour=10, minute=0, tzinfo=fuso_brasilia),   # Edição Matinal
    time(hour=14, minute=30, tzinfo=fuso_brasilia)  # Edição Pós-Atualização Steam
]

# --- SISTEMA DE LOGS ROTATIVO ---
logger = logging.getLogger("Vanilla")
logger.setLevel(logging.INFO)
formatador = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

file_handler = RotatingFileHandler("vanilla.log", maxBytes=5*1024*1024, backupCount=2, encoding="utf-8")
file_handler.setFormatter(formatador)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatador)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False 

# --- INSTÂNCIA DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ==========================================
# 2. MOTOR DE BUSCA E VALIDAÇÃO STEAM
# ==========================================

async def validar_jogo_steam(session, app_id, jogo_cheapshark, adicionados):
    if app_id in adicionados or app_id == "0": 
        return None
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
    
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and data.get(app_id) and data[app_id]['success']:
                    info = data[app_id]['data'].get('price_overview')
                    if info:
                        adicionados.add(app_id)
                        desconto_bruto = float(jogo_cheapshark['savings'])
                        return {
                            'titulo': jogo_cheapshark['title'],
                            'preco_atual': info['final_formatted'],
                            'preco_original': info['initial_formatted'],
                            'desconto_raw': desconto_bruto,
                            'desconto_fmt': f"{desconto_bruto:.0f}%",
                            'popularidade': int(jogo_cheapshark.get('steamRatingCount', 0)),
                            'nota': f"{int(jogo_cheapshark.get('steamRatingPercent', 0))}%",
                            'link': f"https://store.steampowered.com/app/{app_id}"
                        }
    except Exception as e:
        logger.debug(f"Erro ao validar AppID {app_id} na Steam: {e}")
    return None

async def processar_candidatos(session, cand_70, cand_50, limite):
    jogos_validados = []
    adicionados = set()
    
    # Fase 1: Elite (>= 70%)
    for j in cand_70:
        if len(jogos_validados) >= limite: break
        res = await validar_jogo_steam(session, j['steamAppID'], j, adicionados)
        if res: jogos_validados.append(res)
        
    # Fase 2: Preenchimento de Lacunas (>= 50%)
    if len(jogos_validados) < limite:
        for j in cand_50:
            if len(jogos_validados) >= limite: break
            res = await validar_jogo_steam(session, j['steamAppID'], j, adicionados)
            if res: jogos_validados.append(res)
            
    jogos_validados.sort(key=lambda x: x['desconto_raw'], reverse=True)
    return jogos_validados

async def obter_cotacao_dolar(session):
    url = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                dados = await resp.json()
                return float(dados["USDBRL"]["bid"])
    except Exception: 
        pass # Ignora qualquer erro de internet e desce para o retorno seguro
        
    # RETORNO DE SEGURANÇA: Se qualquer coisa der errado na API (ou status != 200), ele sempre retorna 5.50
    return 5.50

async def buscar_promocoes_premium(session):
    c_70, c_50 = [], []
    pagina = 0
    limite_paginas = 5 
    
    while (len(c_70) + len(c_50)) < 40 and pagina < limite_paginas:
        url = f"https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&onSale=1&pageSize=60&pageNumber={pagina}"
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200: break
                dados = await resp.json()
                if not dados: break
        except Exception as e:
            logger.error(f"Erro na API Premium (Página {pagina}): {e}")
            break

        for j in dados:
            if float(j['normalPrice']) >= 14.99 and int(j.get('steamRatingCount', 0)) >= 5000:
                desc = float(j['savings'])
                if desc >= 70.0: c_70.append(j)
                elif desc >= 50.0: c_50.append(j)
        pagina += 1

    return await processar_candidatos(session, c_70, c_50, 20)

async def buscar_promocoes_hype(session):
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Reviews&onSale=1&pageSize=150"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return []
            dados = await resp.json()
    except Exception as e: 
        logger.error(f"Erro na API Hype: {e}")
        return []

    c_70, c_50 = [], []
    for j in dados:
        if int(j.get('steamRatingCount', 0)) >= 40000:
            desc = float(j['savings'])
            if desc >= 70.0: c_70.append(j)
            elif desc >= 50.0: c_50.append(j)

    return await processar_candidatos(session, c_70, c_50, 5)

async def buscar_promocoes_indies(session):
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Deal Rating&onSale=1&pageSize=150"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return []
            dados = await resp.json()
    except Exception as e: 
        logger.error(f"Erro na API Indies: {e}")
        return []

    c_70, c_50 = [], []
    for j in dados:
        if float(j['normalPrice']) <= 20.0 and int(j.get('steamRatingPercent', 0)) >= 92:
            votos = int(j.get('steamRatingCount', 0))
            if 1000 <= votos <= 25000:
                desc = float(j['savings'])
                if desc >= 70.0: c_70.append(j)
                elif desc >= 50.0: c_50.append(j)

    return await processar_candidatos(session, c_70, c_50, 5)


async def obter_aba_ofertas(session):
    url = "https://store.steampowered.com/api/featuredcategories/?cc=br&l=brazilian"
    jogos_filtrados = []
    seen_ids = set()       # Bloqueia IDs duplicados
    seen_titles = set()    # Bloqueia nomes repetidos (edições diferentes com mesmo nome)
    
    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                logger.error(f"API Oficial da Steam Storefront retornou status {response.status}")
                return jogos_filtrados
                
            dados = await response.json()
            specials = dados.get("specials", {})
            items = specials.get("items", [])
            
            for item in items:
                app_id = str(item.get("id", ""))
                titulo = str(item.get("name", "")).strip()
                
                # Validação básica de dados vazios
                if not app_id or app_id == "0" or not titulo:
                    continue
                    
                # 🛡️ FILTRO ANTI-REPETIÇÃO: Se o jogo já passou por aqui, ignora
                if app_id in seen_ids or titulo.lower() in seen_titles:
                    continue
                
                is_discounted = item.get("discounted", False)
                desc_percent = item.get("discount_percent", 0)
                orig_raw = item.get("original_price")
                final_raw = item.get("final_price")
                
                if final_raw is not None:
                    preco_atual_fmt = f"R$ {final_raw / 100:.2f}".replace('.', ',')
                else:
                    preco_atual_fmt = "Gratuito" if not is_discounted else "Consultar"
                    
                if orig_raw is not None:
                    preco_orig_fmt = f"R$ {orig_raw / 100:.2f}".replace('.', ',')
                else:
                    preco_orig_fmt = "--"
                
                if final_raw == 0 and not is_discounted:
                    preco_atual_fmt = "Gratuito"

                # Registra o jogo nos históricos antes de salvar na lista final
                seen_ids.add(app_id)
                seen_titles.add(titulo.lower())

                jogos_filtrados.append({
                    "id": app_id,
                    "titulo": titulo,
                    "preco_atual": preco_atual_fmt,
                    "preco_original": preco_orig_fmt,
                    "desconto_fmt": f"{desc_percent}%" if desc_percent > 0 else "Promo",
                    "link": f"https://store.steampowered.com/app/{app_id}"
                })
                
    except Exception as e:
        logger.error(f"Erro crítico ao puxar ofertas direto da API Steam: {e}", exc_info=True)
        
    return jogos_filtrados

# ==========================================
# 3. EVENTOS E TAREFAS AUTOMÁTICAS (CORRIGIDO ANTI-LIMITES)
# ==========================================

@bot.event
async def on_ready():
    logger.info(f"✅ Vanilla Engine online como {bot.user}")
    if not jornal_da_manha.is_running():
        jornal_da_manha.start()
        logger.info("🕒 Sistema de loops agendados inicializado.")

@tasks.loop(time=HORARIOS_JORNAL)
async def jornal_da_manha():
    canal = bot.get_channel(ID_CANAL_OFERTAS)
    if not canal: 
        logger.error(f"Canal de ofertas {ID_CANAL_OFERTAS} não foi encontrado.")
        return

    logger.info("Iniciando varredura automatizada para a edição do Jornal...")
    async with aiohttp.ClientSession() as session:
        lista_premium = await buscar_promocoes_premium(session)
        lista_hype = await buscar_promocoes_hype(session)
        lista_indies = await buscar_promocoes_indies(session)
        lista_vitrine = await obter_aba_ofertas(session)

    if not any([lista_premium, lista_hype, lista_indies, lista_vitrine]):
        logger.warning("Nenhuma promoção válida encontrada para a edição atual.")
        return

    data_hoje = datetime.now(fuso_brasilia).strftime('%d/%m/%Y')
    hora_atual = datetime.now(fuso_brasilia).hour
    tipo_edicao = "Edição Matinal" if hora_atual < 12 else "Edição do Almoço / Atualização Steam"
    
    # ------------------------------------------
    # EMBED 1: O Top 10 Elite (Dividido para evitar erro de 1024 caracteres)
    # ------------------------------------------
    embed_principal = discord.Embed(
        title=f"📰 VANILLA DAILY • {tipo_edicao} ({data_hoje})",
        description="Filtramos o banco de dados global para trazer a elite dos descontos diretamente para o servidor.",
        color=COR_PRINCIPAL
    )
    
    if lista_premium:
        try:
            id_capa = lista_premium[0]['link'].split('/')[-1]
            embed_principal.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{id_capa}/header.jpg")
        except Exception: pass

    linhas_top10 = []
    for i, j in enumerate(lista_premium[:10]):
        titulo = j.get('titulo', 'Jogo Desconhecido')
        desc_fmt = j.get('desconto_fmt', '0%')
        p_at = j.get('preco_atual', 'N/A')
        p_or = j.get('preco_original', 'N/A')
        link = j.get('link', 'https://store.steampowered.com')
        
        line = f"{EMOJIS_RANK[i]} **[{titulo}]({link})**\n└ 📉 `{desc_fmt} OFF` | 💰 **{p_at}** *(De: {p_or})*"
        linhas_top10.append(line)

    # 🛡️ Correção do Limite: Divisão cirúrgica em blocos de no máximo 5 jogos
    if linhas_top10:
        metade_1 = linhas_top10[:5]
        metade_2 = linhas_top10[5:]

        embed_principal.add_field(
            name="🏆 HIGHLIGHTS: TOP 1 ao 5", 
            value="\n".join(metade_1), 
            inline=False
        )
        if metade_2:
            embed_principal.add_field(
                name="🏅 HIGHLIGHTS: TOP 6 ao 10", 
                value="\n".join(metade_2), 
                inline=False
            )
    else:
        embed_principal.add_field(
            name="🏆 HIGHLIGHTS: TOP 10 DE HOJE",
            value="Nenhum grande destaque processado.",
            inline=False
        )
        
    await canal.send(embed=embed_principal)

    # ------------------------------------------
    # EMBED 2: Vitrine de Ofertas (Aba Oficial Steam)
    # ------------------------------------------
    if lista_vitrine:
        embed_vitrine = discord.Embed(
            title="🎮 VITRINE DE OFERTAS DA STEAM",
            description="Destaques oficiais extraídos diretamente da aba de ofertas da loja (Sincronização Direta):",
            color=0x1b2838
        )
        
        try:
            primeiro_app_id = lista_vitrine[0]['id']
            embed_vitrine.set_thumbnail(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{primeiro_app_id}/header.jpg")
        except Exception: pass
        
        linhas_vitrine = []
        # Mantido em 5 para segurança total de tamanho de dados
        for j in lista_vitrine[:5]:
            titulo = j.get('titulo', 'Jogo em Destaque')
            desc_fmt = j.get('desconto_fmt', 'Promo')
            p_at = j.get('preco_atual', 'Consultar')
            p_or = j.get('preco_original', '--')
            link = j.get('link', 'https://store.steampowered.com')

            line = f"🔹 **{titulo}**\n└ 📉 `{desc_fmt} OFF` | 💰 **{p_at}** *(De: {p_or})* • [🛒 Comprar]({link})"
            linhas_vitrine.append(line)
            
        embed_vitrine.add_field(
            name="🔥 Em Destaque na Página Principal",
            value="\n\n".join(linhas_vitrine),
            inline=False
        )
        await canal.send(embed=embed_vitrine)

    # ------------------------------------------
    # EMBED 3: Suplemento Especial (Hype & Indies)
    # ------------------------------------------
    if lista_hype or lista_indies:
        embed_suplemento = discord.Embed(title="🎯 SUPLEMENTO ESPECIAL", color=COR_SUCESSO)
        
        if lista_hype:
            texto_hype = ""
            for j in lista_hype[:3]:
                t = j.get('titulo', 'AAA')
                l = j.get('link', 'https://store.steampowered.com')
                d = j.get('desconto_fmt', '-%')
                p = j.get('preco_atual', 'N/A')
                texto_hype += f"🔥 **[{t}]({l})**\n└ `{d} OFF` | **{p}**\n"
            embed_suplemento.add_field(name="🚀 Blockbusters de Peso", value=texto_hype, inline=False)

        if lista_indies:
            texto_indies = ""
            for j in lista_indies[:3]:
                t = j.get('titulo', 'Indie')
                l = j.get('link', 'https://store.steampowered.com')
                n = j.get('nota', '90%')
                p = j.get('preco_atual', 'N/A')
                texto_indies += f"💎 **[{t}]({l})** (Nota: `{n}`)\n└ `🏷️ {p}`\n"
            embed_suplemento.add_field(name="💎 Joias Escondidas (Indies)", value=texto_indies, inline=False)

        embed_suplemento.set_footer(text="Vanilla Engine • Relatório Diário Automatizado")
        await canal.send(embed=embed_suplemento)
    
    logger.info(f"Sucesso: {tipo_edicao} publicada com tratamento de tamanho de strings.")


# ==========================================
# 4. COMPONENTES DE INTERFACE DE USUÁRIO (UI)
# ==========================================

class MenuOfertas(discord.ui.Select):
    def __init__(self, jogos):
        self.jogos = jogos
        opcoes = [
            discord.SelectOption(
                label=f"{i+1}. {jogo['titulo']}"[:100],
                description=f"Por {jogo['preco_atual']} ({jogo['desconto_fmt']} OFF)",
                value=str(i),
                emoji="🎮"
            ) for i, jogo in enumerate(jogos)
        ]
        super().__init__(placeholder="Selecione um jogo para inspecionar os detalhes...", min_values=1, max_values=1, options=opcoes)

    async def callback(self, interaction: discord.Interaction):
        jogo = self.jogos[int(self.values[0])]
        try:
            app_id = jogo['link'].split('/')[-1]
        except Exception:
            app_id = "0"
        
        embed = discord.Embed(title=jogo['titulo'], color=COR_PRINCIPAL)
        if app_id != "0":
            embed.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg")
        
        alerta = "🚨 **MAIOR DESCONTO DO HISTÓRICO!**\n" if jogo['desconto_raw'] >= 90 else ""
        embed.description = (
            f"{alerta}\n"
            f"📉 **Desconto:** `{jogo['desconto_fmt']}`\n"
            f"💰 **Preço Atual:** {jogo['preco_atual']}\n"
            f"❌ **Preço Original:** ~~{jogo['preco_original']}~~\n"
            f"📊 **Avaliações (Steam):** `{jogo['popularidade']:,}` análises"
        )
        embed.add_field(name="Loja Oficial", value=f"[Adicionar à Biblioteca]({jogo['link']})")
        await interaction.response.edit_message(embed=embed, view=self.view)

class PainelOfertasView(discord.ui.View):
    def __init__(self, jogos):
        super().__init__(timeout=180)
        self.add_item(MenuOfertas(jogos))


# ==========================================
# 5. COMANDOS DO USUÁRIO
# ==========================================

@bot.command(name="ofertas")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def ofertas(ctx):
    logger.info(f"Comando !ofertas invocado por {ctx.author}.")
    feedback = await ctx.send("🔍 *Compilando o relatório analítico de ofertas ativas...*")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_premium(session)
    await feedback.delete()

    if not jogos:
        return await ctx.send("❌ O radar não detectou ofertas qualificadas no momento.")

    # Listagem consolidada para evitar estouro de caracteres (Polimento Mobile)
    linhas_descricao = []
    for i, j in enumerate(jogos):
        rank = EMOJIS_RANK[i] if i < 10 else f"🏅 **{i+1}.**"
        line = f"{rank} **{j['titulo']}**\n└ 📉 `{j['desconto_fmt']} OFF` | 💰 **{j['preco_atual']}** *(De: {j['preco_original']})*"
        linhas_descricao.append(line)

    embed_lista = discord.Embed(
        title=f"🎮 Top {len(jogos)} Melhores Ofertas Premium", 
        description="Ordenadas com foco na qualidade técnica e maior margem de desconto:\n\n" + "\n".join(linhas_descricao),
        color=COR_PRINCIPAL
    )
    embed_lista.set_footer(text="Use o menu de seleção abaixo para abrir os detalhes de um título.")
    await ctx.send(embed=embed_lista, view=PainelOfertasView(jogos))


@bot.command(name="buscar")
async def buscar(ctx, *, nome_jogo: str):
    logger.info(f"Comando !buscar acionado para: '{nome_jogo}'")
    msg = await ctx.send(f"🔎 Consultando indexadores concorrentes para **{nome_jogo}**...")
    
    try:
        async with aiohttp.ClientSession() as session:
            url_busca = f"https://www.cheapshark.com/api/1.0/games?title={nome_jogo.replace(' ', '%20')}&limit=1"
            async with session.get(url_busca) as resp:
                d_busca = await resp.json()

            if not d_busca:
                return await msg.edit(content=f"❌ '{nome_jogo}' não foi encontrado na base de dados.")

            g_id, app_id, titulo, p_usd = d_busca[0].get('gameID'), d_busca[0].get('steamAppID'), d_busca[0].get('external'), float(d_busca[0].get('cheapest', 0))
            if not app_id or app_id == "0":
                return await msg.edit(content=f"ℹ️ **{titulo}** não possui indexação direta na Steam.")

            url_hist = f"https://www.cheapshark.com/api/1.0/games?id={g_id}"
            async with session.get(url_hist) as resp_h: 
                d_hist = await resp_h.json()
            
            cotacao = await obter_cotacao_dolar(session)
            hist = d_hist.get('cheapestPriceEver', {})
            m_usd, m_brl, t_m = float(hist.get('price', 0)), float(hist.get('price', 0)) * cotacao, hist.get('date', 0)
            data_m = datetime.fromtimestamp(t_m).strftime('%d/%m/%Y') if t_m else "Desconhecida"

            lojas_txt = "".join([f"🏪 **{LOJAS_CHEAPSHARK[d['storeID']]}**: US$ {float(d['price']):.2f} - [Acessar Loja](https://www.cheapshark.com/redirect?dealID={d['dealID']})\n" for d in d_hist.get('deals', []) if d['storeID'] in LOJAS_CHEAPSHARK and d['storeID'] != "1"])

            url_st = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&filters=price_overview"
            async with session.get(url_st) as resp_st:
                d_st = await resp_st.json()
                if not d_st or not d_st.get(app_id) or not d_st[app_id]['success']:
                    return await msg.edit(content=f"❌ Falha ao sincronizar a moeda regional BRL para **{titulo}**.")

                info = d_st[app_id]['data'].get('price_overview')
                emb = discord.Embed(title=titulo, color=COR_PRINCIPAL)
                emb.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg")

                if info:
                    p_at, p_or, desc = info['final_formatted'], info['initial_formatted'], info.get('discount_percent', 0)
                    emb.description = f"🔥 **Promoção Ativa!**\n└ De: ~~{p_or}~~ por **{p_at}** (`-{desc}%`)\n\n" if desc > 0 else f"💰 Preço Atual: **{p_at}** (Preço base s/ desconto)\n\n"
                    emb.description += f"🏆 **Aviso:** Este valor bate com a mínima histórica! (Est. R$ {m_brl:.2f})" if p_usd <= m_usd else f"📉 Mínima Histórica Registrada: **R$ {m_brl:.2f}** em {data_m}."
                else: 
                    emb.description = "ℹ️ Este título é gratuito ou não possui um preço base ativo na plataforma."

                if lojas_txt: 
                    emb.add_field(name="🌍 Alternativas Externas (Conversão Direta)", value=lojas_txt, inline=False)
                emb.add_field(name="Biblioteca Principal", value=f"[Abrir Página Oficial na Steam](https://store.steampowered.com/app/{app_id})", inline=False)
                
                await msg.delete()
                await ctx.send(embed=emb)

    except Exception as e:
        logger.error(f"Falha de execução no comando !buscar: {e}", exc_info=True)
        await msg.edit(content="⚠️ Ocorreu uma anomalia interna ao processar a busca.")


@bot.command(name="hype")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def hype(ctx):
    feedback = await ctx.send("🚀 *Filtrando banco de dados por contagem de engajamento massivo...*")
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_hype(session)
    await feedback.delete()
    
    if not jogos: 
        return await ctx.send("❌ Nenhum Triple-A com engajamento expressivo preencheu os requisitos hoje.")

    embed = discord.Embed(title="🚀 Radar de Heavy Hype", description="Blockbusters de alta relevância com corte expressivo no preço:", color=COR_HYPE)
    for i, j in enumerate(jogos):
        embed.add_field(
            name=f"{EMOJIS_RANK[i] if i < len(EMOJIS_RANK) else '🔹'} {j['titulo']}", 
            value=f"💰 **{j['preco_atual']}** (~~{j['preco_original']}~~) | 📉 `{j['desconto_fmt']} OFF`\n🔗 [Ir para a Loja]({j['link']})", 
            inline=False
        )
    await ctx.send(embed=embed)


@bot.command(name="indies")
@commands.cooldown(1, 30, commands.BucketType.guild)
async def indies(ctx):
    feedback = await ctx.send("💎 *Garimpando joias escondidas com alto índice de aclamação...*")
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_indies(session)
    await feedback.delete()
    
    if not jogos: 
        return await ctx.send("❌ O garimpo mercadológico não encontrou títulos Indie qualificados nesta janela.")

    embed = discord.Embed(title="💎 Joias Escondidas", description="Títulos independentes altamente aclamados pela crítica comunitária:", color=COR_SUCESSO)
    for i, j in enumerate(jogos):
        embed.add_field(
            name=f"{EMOJIS_RANK[i] if i < len(EMOJIS_RANK) else '🔹'} {j['titulo']}", 
            value=f"⭐ Aprovação: `{j['nota']}`\n└ 💰 **{j['preco_atual']}** | 📉 `{j['desconto_fmt']} OFF`\n🔗 [Ir para a Loja]({j['link']})", 
            inline=False
        )
    await ctx.send(embed=embed)


# ==========================================
# 6. ADMINISTRAÇÃO & SUPORTE
# ==========================================

@bot.command(name="forcarjornal")
@commands.is_owner()
async def forcar_jornal(ctx):
    msg = await ctx.send("⚙️ *Comando administrativo detectado. Sincronizando e forçando rotina...*")
    await jornal_da_manha()
    await msg.edit(content="✅ **Rotina diária executada com sucesso manual.**")


if __name__ == "__main__":
    bot.run(TOKEN)