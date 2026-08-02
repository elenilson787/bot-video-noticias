import os, json, asyncio, requests, subprocess
from google import genai
from pyrogram import Client
import trafilatura

# 1. Extrai a notícia
url = os.getenv("NEWS_URL")
downloaded = trafilatura.fetch_url(url)
texto_noticia = trafilatura.extract(downloaded)

# 2. Gera o Roteiro Ajustado para 7-9 Minutos com Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
prompt = f"""
Você é um roteirista documental profissional. Com base no texto a seguir, crie um roteiro completo de 1.100 a 1.300 palavras (para um vídeo de 8 minutos).
Divida o conteúdo em exatamente 8 blocos narrativos.

Retorne ESTRITAMENTE um JSON no seguinte formato:
[
  {{
    "bloco": 1,
    "narracao": "Texto longo narrado para este trecho...",
    "keywords_ingles": ["word1", "word2", "word3"]
  }},
  ...
]

Notícia: {texto_noticia}
"""

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt,
    config={'response_mime_type': 'application/json'}
)
roteiro = json.loads(response.text)

# 3. Processamento de Áudio (edge-tts) e Imagens por Bloco
async def processar_midias():
    os.makedirs("output", exist_ok=True)
    concat_list = []
    
    for idx, bloco in enumerate(roteiro):
        audio_path = f"output/audio_{idx}.mp3"
        video_part = f"output/part_{idx}.mp4"
        
        # Gerar Voz
        cmd_tts = f'edge-tts --text "{bloco["narracao"]}" --voice "pt-BR-AntonioNeural" --write-media {audio_path}'
        subprocess.run(cmd_tts, shell=True, check=True)
        
        # Buscar 1 Imagem/Vídeo no Pexels para o bloco
        kw = "+".join(bloco["keywords_ingles"])
        p_res = requests.get(
            f"https://api.pexels.com/v1/search?query={kw}&per_page=1",
            headers={"Authorization": os.getenv("PEXELS_API_KEY")}
        ).json()
        
        img_url = p_res['photos'][0]['src']['landscape'] if p_res.get('photos') else "https://picsum.photos/1920/1080"
        img_data = requests.get(img_url).content
        img_path = f"output/img_{idx}.jpg"
        with open(img_path, "wb") as f: f.write(img_data)
        
        # Renderizar Bloco via FFmpeg (Sem estourar RAM)
        cmd_ffmpeg = (
            f'ffmpeg -y -loop 1 -i {img_path} -i {audio_path} '
            f'-c:v libx264 -tune stillimage -c:a aac -b:a 192k -pix_fmt yuv420p '
            f'-shortest {video_part}'
        )
        subprocess.run(cmd_ffmpeg, shell=True, check=True)
        concat_list.append(f"file 'part_{idx}.mp4'")

    # Lista para juntar todas as partes
    with open("output/files.txt", "w") as f:
        f.write("\n".join(concat_list))

    # Unir todos os blocos no vídeo final de 8 minutos
    cmd_join = "ffmpeg -y -f concat -safe 0 -i output/files.txt -c copy final_video.mp4"
    subprocess.run(cmd_join, shell=True, check=True)

asyncio.run(processar_midias())

# 4. Enviar para o Telegram via Pyrogram (> 50MB)
async def enviar_telegram():
    app = Client(
        "bot_session",
        api_id=os.getenv("TELEGRAM_API_ID"),
        api_hash=os.getenv("TELEGRAM_API_HASH"),
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN")
    )
    async with app:
        await app.send_video(
            chat_id=int(os.getenv("CHAT_ID")),
            video="final_video.mp4",
            caption=f"🎥 Vídeo de notícias concluído (~8 minutos)!\nFonte: {url}"
        )

asyncio.run(enviar_telegram())
