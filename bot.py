import discord
import os
import aiohttp
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, datetime

# ==========================================
# 1. CONFIGURAÇÕES INICIAIS E VARIÁVEIS
# ==========================================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Substitua pelo ID do canal onde o bot vai postar o jornal diário
ID_CANAL_OFERTAS = 123456789012345678 
HORARIO_POSTAGEM = time(hour=10, minute=0)

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
        print(f"Erro na API CheapShark: {e}")
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
        except:
            continue
            
    return jogos_filtrados

# ==========================================
# 3. EVENTOS DO SISTEMA
# ==========================================
@bot.event
async def on_ready():
    print(f'✅ Sistema operacional! Conectado como {bot.user.name}')
    
    if not jornal_da_manha.is_running():
        jornal_da_manha.start()
        print("🕒 Automação diária agendada com sucesso.")

# ==========================================
# 4. TAREFAS AUTOMATIZADAS (BACKGROUND)
# ==========================================
@tasks.loop(time=HORARIO_POSTAGEM)
async def jornal_da_manha():
    canal = bot.get_channel(ID_CANAL_OFERTAS)
    if not canal:
        print("❌ Erro na automação: ID do canal de ofertas inválido ou não encontrado.")
        return

    print(f"⏰ {datetime.now().strftime('%H:%M')} - Iniciando varredura diária...")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_premium(session)

    if jogos:
        embed = discord.Embed(
            title="🗞️ Jornal Vanilla: As Melhores de Hoje",
            description="Bom dia! O radar identificou estas ofertas premium para hoje:",
            color=0x1b2838
        )
        emojis_rank = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, jogo in enumerate(jogos):
            alerta = "🚨 **PECHINCHA!** " if jogo['desconto_raw'] >= 90 else ""
            embed.add_field(
                name=f"{emojis_rank[i]} {jogo['titulo']}",
                value=f"💰 {alerta}De: ~~{jogo['preco_original']}~~ por **{jogo['preco_atual']}**\n🔗 [Acessar a Oferta]({jogo['link']})",
                inline=False
            )
        embed.set_footer(text=f"Varredura Automática • {datetime.now().strftime('%d/%m/%Y')}")
        await canal.send(embed=embed)

# ==========================================
# 5. COMANDOS DO USUÁRIO
# ==========================================
@bot.command(name="ofertas")
@commands.cooldown(1, 60, commands.BucketType.guild)
async def ofertas(ctx):
    """Retorna o Top 10 atual de ofertas da Steam."""
    feedback = await ctx.send("🔍 *Processando dados do mercado...*")
    
    async with aiohttp.ClientSession() as session:
        jogos = await buscar_promocoes_premium(session)
    
    await feedback.delete()

    if not jogos:
        await ctx.send("❌ O radar não detectou nenhuma oferta nível AAA no momento.")
        return

    embed = discord.Embed(title="🔥 Top 10 Ofertas Premium", color=0x1b2838)
    emojis_rank = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, jogo in enumerate(jogos):
        embed.add_field(
            name=f"{emojis_rank[i]} {jogo['titulo']}",
            value=f"💰 **{jogo['preco_atual']}** (~~{jogo['preco_original']}~~) | 📉 `{jogo['desconto_fmt']}`\n🔗 [Ver na Steam]({jogo['link']})",
            inline=False 
        )
    await ctx.send(embed=embed)

@bot.command(name="buscar")
async def buscar(ctx, *, nome_jogo: str):
    """Busca o preço atual de um jogo específico."""
    msg_espera = await ctx.send(f"🔎 Consultando os servidores da Steam para **{nome_jogo}**...")

    try:
        async with aiohttp.ClientSession() as session:
            url_busca = f"https://www.cheapshark.com/api/1.0/games?title={nome_jogo.replace(' ', '%20')}&limit=1"
            async with session.get(url_busca) as resp:
                dados_busca = await resp.json()

            if not dados_busca:
                await msg_espera.edit(content=f"❌ Não encontrei '{nome_jogo}'.")
                return

            steam_app_id = dados_busca[0].get('steamAppID')
            titulo_oficial = dados_busca[0].get('external')

            if not steam_app_id or steam_app_id == "0":
                await msg_espera.edit(content=f"ℹ️ **{titulo_oficial}** não está disponível na Steam.")
                return

            url_steam = f"https://store.steampowered.com/api/appdetails?appids={steam_app_id}&cc=br&filters=price_overview"
            async with session.get(url_steam) as resp_steam:
                dados_steam = await resp_steam.json()
                
                if not dados_steam or not dados_steam.get(steam_app_id) or not dados_steam[steam_app_id]['success']:
                    await msg_espera.edit(content=f"❌ Sem dados de preço para **{titulo_oficial}** na Steam Brasil.")
                    return

                info_preco = dados_steam[steam_app_id]['data'].get('price_overview')
                embed = discord.Embed(title=titulo_oficial, color=0x1b2838)
                embed.set_image(url=f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_app_id}/header.jpg")

                if info_preco:
                    p_atual = info_preco['final_formatted']
                    p_orig = info_preco['initial_formatted']
                    desc = info_preco.get('discount_percent', 0)
                    if desc > 0:
                        embed.description = f"🔥 **Promoção!**\n💰 De: ~~{p_orig}~~ por **{p_atual}**\n📉 Desconto: **{desc}%**"
                    else:
                        embed.description = f"💰 Preço: **{p_atual}**\n*Sem ofertas no momento.*"
                else:
                    embed.description = "ℹ️ Jogo gratuito ou sem preço listado."

                embed.add_field(name="Link", value=f"[Abrir na Loja](https://store.steampowered.com/app/{steam_app_id})", inline=False)
                await msg_espera.delete()
                await ctx.send(embed=embed)

    except Exception as e:
        print(f"Erro na busca: {e}")
        await msg_espera.edit(content="⚠️ Ocorreu um erro interno na busca.")

# ==========================================
# 6. TRATAMENTO DE ERROS E SEGURANÇA
# ==========================================
@ofertas.error
async def ofertas_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Calma lá! Tente novamente em **{error.retry_after:.0f} segundos**.")

# ==========================================
# 7. INICIALIZAÇÃO
# ==========================================
if __name__ == "__main__":
    bot.run(TOKEN)