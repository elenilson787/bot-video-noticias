import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ==============================================================================
# --- PREENCHA SUAS CREDENCIAIS AQUI ---
# ==============================================================================
GITHUB_TOKEN = "ghp_SEU_TOKEN_PAT_DO_GITHUB"
REPO_OWNER = "seu-usuario-github"
REPO_NAME = "bot-video-noticias"
TELEGRAM_BOT_TOKEN = "SEU_BOT_TOKEN_DO_BOTFATHER"
# ==============================================================================

async def disparar_github(update: Update, news_url: str):
    """Envia a requisição de disparo (repository_dispatch) para o GitHub Actions"""
    chat_id = update.message.chat_id
    await update.message.reply_text("🚀 Link recebido! Disparando o GitHub Actions para renderizar o vídeo...")

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    payload = {
        "event_type": "render_video",
        "client_payload": {
            "news_url": news_url,
            "chat_id": chat_id
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 204:
            print(f"✅ Disparo enviado com sucesso para a URL: {news_url}")
        else:
            print(f"❌ Erro ao disparar GitHub Actions. Código: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"⚠️ Falha de conexão com a API do GitHub: {e}")

async def comando_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata mensagens enviadas com /video <link>"""
    news_url = context.args[0] if context.args else None
    if news_url:
        await disparar_github(update, news_url)
    else:
        await update.message.reply_text("Cole o link da notícia após o comando. Exemplo:\n/video https://g1.globo.com/...")

async def receber_link_direto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata mensagens que contêm apenas o link direto (http/https) sem o comando /video"""
    texto = update.message.text.strip()
    if texto.startswith("http://") or texto.startswith("https://"):
        await disparar_github(update, texto)

if __name__ == "__main__":
    print("\n🤖 Bot Gatilho iniciado e online!")
    print("Pronto para receber links no Telegram!\n")
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Suporta tanto /video <link> quanto colar o link diretamente no chat
    app.add_handler(CommandHandler("video", comando_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_direto))
    
    app.run_polling()
