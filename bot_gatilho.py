import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- SERVIDOR HTTP SIMPLIFICADO PARA O PLANO GRATUITO DO RENDER ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot online!")

def rodar_servidor_http():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

# Inicia o servidor HTTP em segundo plano para o Render não fechar a aplicação
threading.Thread(target=rodar_servidor_http, daemon=True).start()

# ==============================================================================
# --- LEITURA SEGURA VIA VARIÁVEIS DE AMBIENTE ---
# ==============================================================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER", "elenilson787")
REPO_NAME = os.getenv("REPO_NAME", "bot-video-noticias")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# ==============================================================================

async def disparar_github(update: Update, news_url: str):
    """Envia a requisição de disparo (repository_dispatch) para o GitHub Actions"""
    chat_id = update.message.chat_id

    if not GITHUB_TOKEN or not TELEGRAM_BOT_TOKEN:
        await update.message.reply_text("❌ Erro de configuração: Tokens não encontrados nas variáveis de ambiente.")
        print("❌ Faltam variáveis de ambiente (GITHUB_TOKEN ou TELEGRAM_BOT_TOKEN).")
        return

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
        # Executamos a requisição de forma assíncrona sem travar a thread do Telegram
        response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 204:
            print(f"✅ Disparo enviado com sucesso para a URL: {news_url}")
            await update.message.reply_text("⚡ Pipeline ativado no GitHub Actions! O vídeo será gerado e enviado aqui em alguns minutos.")
        else:
            erro_msg = f"❌ Erro ao acionar o GitHub Actions (Status: {response.status_code})."
            print(f"{erro_msg} Detalhes: {response.text}")
            await update.message.reply_text(f"{erro_msg}\nVerifique as permissões do seu `GITHUB_TOKEN`.")
    except Exception as e:
        print(f"⚠️ Falha de conexão com a API do GitHub: {e}")
        await update.message.reply_text(f"⚠️ Falha de conexão ao comunicar com o GitHub: {e}")

async def comando_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_url = context.args[0] if context.args else None
    if news_url:
        await disparar_github(update, news_url)
    else:
        await update.message.reply_text("Cole o link da notícia após o comando. Exemplo:\n/video https://g1.globo.com/...")

async def receber_link_direto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if texto.startswith("http://") or texto.startswith("https://"):
        await disparar_github(update, texto)

if __name__ == "__main__":
    print("\n🤖 Bot Gatilho iniciado e online!")
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERRO CRÍTICO: A variável TELEGRAM_BOT_TOKEN não foi definida!")
        exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("video", comando_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_direto))
    
    app.run_polling()
