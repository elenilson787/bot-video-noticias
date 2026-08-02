import os
import json
import asyncio
import requests
import subprocess
from openai import OpenAI
from pyrogram import Client
import trafilatura

async def main():
    # 1. Leitura e Validação de Variáveis de Ambiente
    news_url = os.getenv("NEWS_URL")
    chat_id = os.getenv("CHAT_ID")
    openai_key = os.getenv("OPENAI_API_KEY")
    pexels_key = os.getenv("PEXELS_API_KEY")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([news_url, chat_id, openai_key, pexels_key, telegram_token, telegram_api_id, telegram_api_hash]):
        raise ValueError("❌ Erro: Uma ou mais variáveis de ambiente obrigatórias não foram encontradas nas Secrets!")

    print(f"📥 Extraindo texto da notícia: {news_url}")
    
    # 2. Extração da Notícia com Trafilatura
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Geração do Roteiro na OpenAI API (gpt-4o-mini)
    print("🤖 Solicitando roteiro estruturado à OpenAI...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um roteirista documental profissional. Com base no texto a seguir, crie um roteiro completo de 1.100 a 1.300 palavras (para um vídeo de 8 minutos).
    Divida o conteúdo em exatamente 8 blocos narrativos.

    Retorne ESTRITAMENTE um JSON com a chave "roteiro" no seguinte formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado para este trecho...",
          "keywords_ingles": ["word1", "word2", "word3"]
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
    print(f"✅ Roteiro gerado com sucesso via OpenAI! Total de blocos: {len(roteiro)}")

    # 4. Geração de Mídias (Áudio + Imagem) e Renderização dos Blocos
    os.makedirs("output", exist_ok=True)
    concat_list = []

    for idx, bloco in enumerate(roteiro):
        print(f"🎬 Processando Bloco {idx + 1}/{len(roteiro)}...")
        
        audio_path = os.path.abspath(f"output/audio_{idx}.mp3")
        img_path = os.path.abspath(f"output/img_{idx}.jpg")
        video_part = os.path.abspath(f"output/part_{idx}.mp4")

        # A. Gerar Voz com edge-tts
        cmd_tts = [
            "edge-tts",
            "--text", bloco["narracao"],
            "--voice", "pt-BR-AntonioNeural",
            "--write-media", audio_path
        ]
        subprocess.run(cmd_tts, check=True)

        # B. Buscar Imagem de fundo no Pexels
        keywords = "+".join(bloco.get("keywords_ingles", ["news"]))
        try:
            headers = {"Authorization": pexels_key}
            p_res = requests.get(
                f"https://api.pexels.com/v1/search?query={keywords}&per_page=1",
                headers=headers,
                timeout=10
            ).json()
            
            if p_res.get('photos') and len(p_res['photos']) > 0:
                img_url = p_res['photos'][0]['src']['landscape']
            else:
                img_url = "https://picsum.photos/1920/1080"
        except Exception as e:
            print(f"⚠️ Erro/Timeout na busca no Pexels ({e}). Usando imagem genérica.")
            img_url = "https://picsum.photos/1920/1080"

        img_data = requests.get(img_url, timeout=10).content
        with open(img_path, "wb") as f:
            f.write(img_data)

        # C. Renderizar o Bloco de Vídeo via FFmpeg
        cmd_ffmpeg = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest", video_part
        ]
        subprocess.run(cmd_ffmpeg, check=True)
        
        concat_list.append(f"file '{video_part}'")

    # 5. Concatenar Todos os Blocos Renderizados
    list_file_path = os.path.abspath("output/files.txt")
    final_video_path = os.path.abspath("final_video.mp4")

    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_list))

    print("🔄 Unindo blocos em um único vídeo final...")
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

    # 6. Enviar Arquivo Final para o Telegram (Até 2 GB via Pyrogram)
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
