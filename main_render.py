import os
import json
import asyncio
import requests
import subprocess
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import OpenAI
from pyrogram import Client
import trafilatura

def buscar_imagem_web(query):
    """Busca mídias reais da web (Google/DuckDuckGo) baseadas na notícia"""
    try:
        results = DDGS().images(keywords=query, max_results=3)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception as e:
        print(f"⚠️ Erro ao buscar imagem na web para '{query}': {e}")
    return "https://picsum.photos/1920/1080"

def extrair_foto_capa_noticia(url):
    """Extrai a foto de capa original do site da notícia (Open Graph)"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
    except Exception as e:
        print(f"⚠️ Não foi possível extrair a foto de capa original: {e}")
    return None

async def main():
    # 1. Leitura de Variáveis de Ambiente
    news_url = os.getenv("NEWS_URL")
    chat_id = os.getenv("CHAT_ID")
    openai_key = os.getenv("OPENAI_API_KEY")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([news_url, chat_id, openai_key, telegram_token, telegram_api_id, telegram_api_hash]):
        raise ValueError("❌ Erro: Variáveis de ambiente obrigatórias não encontradas!")

    print(f"📥 Extraindo texto da notícia: {news_url}")
    foto_capa_original = extrair_foto_capa_noticia(news_url)

    # 2. Extração da Notícia
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Geração do Roteiro na OpenAI API
    print("🤖 Solicitando roteiro estruturado à OpenAI...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um roteirista documental profissional de notícias. Com base no texto a seguir, crie um roteiro completo de 1.100 a 1.300 palavras (para um vídeo de 8 minutos).
    Divida o conteúdo em exatamente 8 blocos narrativos.

    Para cada bloco, crie um termo de busca preciso em português para encontrar imagens reais da notícia no Google (ex: "Lula discurso convencao PT", "Palácio do Planalto Brasília", etc).

    Retorne ESTRITAMENTE um JSON no seguinte formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado para este trecho...",
          "termo_busca_imagem": "termo especifico de busca em portugues"
        }}
      ]
    }}

    Notícia:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um gerador de roteiros que responde exclusivamente no formato JSON solicitado."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    roteiro = dados["roteiro"]
    print(f"✅ Roteiro gerado com sucesso! Total de blocos: {len(roteiro)}")

    # 4. Processamento das Mídias e Renderização dos Blocos
    os.makedirs("output", exist_ok=True)
    concat_list = []

    for idx, bloco in enumerate(roteiro):
        print(f"🎬 Processando Bloco {idx + 1}/{len(roteiro)}...")
        
        audio_path = os.path.abspath(f"output/audio_{idx}.mp3")
        media_path = os.path.abspath(f"output/media_{idx}")
        video_part = os.path.abspath(f"output/part_{idx}.mp4")

        # A. Gerar Voz com edge-tts
        cmd_tts = [
            "edge-tts",
            "--text", bloco["narracao"],
            "--voice", "pt-BR-AntonioNeural",
            "--write-media", audio_path
        ]
        subprocess.run(cmd_tts, check=True)

        # B. Selecionar Imagem/Vídeo
        if idx == 0 and foto_capa_original:
            media_url = foto_capa_original
            print("📸 Usando a foto de capa original para o Bloco 1.")
        else:
            termo = bloco.get("termo_busca_imagem", "noticia brasil")
            print(f"🔎 Buscando mídia real para: '{termo}'")
            media_url = buscar_imagem_web(termo)

        # Identifica se a URL é vídeo ou imagem
        is_video = any(media_url.lower().endswith(ext) for ext in ['.mp4', '.webm', '.mov'])
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            media_data = requests.get(media_url, headers=headers, timeout=10).content
            ext = ".mp4" if is_video else ".jpg"
            media_file = media_path + ext
            with open(media_file, "wb") as f:
                f.write(media_data)
        except Exception as e:
            print(f"⚠️ Falha ao baixar mídia de '{media_url}'. Usando imagem estática padrão.")
            is_video = False
            media_file = media_path + ".jpg"
            fallback_data = requests.get("https://picsum.photos/1920/1080").content
            with open(media_file, "wb") as f:
                f.write(fallback_data)

        # C. Configurar Filtros de Edição no FFmpeg
        if is_video:
            # Vídeo: Sem Zoom, apenas escala e corte
            print("🎥 Mídia identificada como VÍDEO (sem zoom aplicado).")
            cmd_ffmpeg = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", media_file,
                "-i", audio_path,
                "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p", "-shortest", video_part
            ]
        else:
            # Imagem: Aplica Zoom In ou Zoom Out alternadamente
            if idx % 2 == 0:
                print("🔍 Aplicando filtro: ZOOM IN")
                zoom_filter = "scale=2560:1440,zoompan=z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080,fps=25"
            else:
                print("🔎 Aplicando filtro: ZOOM OUT")
                zoom_filter = "scale=2560:1440,zoompan=z='max(1.25-zoom*0.0015,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080,fps=25"

            cmd_ffmpeg = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", media_file,
                "-i", audio_path,
                "-vf", zoom_filter,
                "-c:v", "libx264", "-tune", "stillimage",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p", "-shortest", video_part
            ]

        subprocess.run(cmd_ffmpeg, check=True)
        concat_list.append(f"file '{video_part}'")

    # 5. Concatenar Blocos no Vídeo Final
    list_file_path = os.path.abspath("output/files.txt")
    final_video_path = os.path.abspath("final_video.mp4")

    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_list))

    print("🔄 Unindo blocos no vídeo final...")
    cmd_join = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file_path,
        "-c", "copy",
        final_video_path
    ]
    subprocess.run(cmd_join, check=True)
    print("🎉 Vídeo final montado com sucesso!")

    # 6. Enviar para o Telegram via Pyrogram
    print("📤 Enviando vídeo final no Telegram...")
    app = Client(
        "bot_session",
        api_id=int(telegram_api_id),
        api_hash=telegram_api_hash,
        bot_token=telegram_token
    )

    async with app:
        await app.send_video(
            chat_id=int(chat_id),
            video=final_video_path,
            caption=f"🎥 Vídeo de notícias concluído (~8 minutos)!\nFonte: {news_url}"
        )
    print("✅ Envio concluído com sucesso!")

if __name__ == "__main__":
    asyncio.run(main())
