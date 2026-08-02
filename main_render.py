import os
import json
import math
import asyncio
import requests
import subprocess
from io import BytesIO
from PIL import Image
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import OpenAI
from pyrogram import Client
import trafilatura

def get_audio_duration(audio_path):
    """Retorna a duração exata do áudio em segundos usando ffprobe"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def salvar_imagem_valida(binary_content, target_path):
    """Valida se o conteúdo é uma imagem real e converte para JPEG RGB puro"""
    try:
        img = Image.open(BytesIO(binary_content))
        img = img.convert('RGB')
        img.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Imagem descartada/corrompida: {e}")
        return False

def buscar_imagem_web(query):
    """Busca mídias reais da web focadas em jornalismo/fatos reais"""
    query_jornalistica = f"{query} foto noticia"
    try:
        results = DDGS().images(keywords=query_jornalistica, max_results=5)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception as e:
        print(f"⚠️ Erro ao buscar imagem para '{query}': {e}")
    return "https://picsum.photos/1920/1080"

def extrair_foto_capa_noticia(url):
    """Extrai a foto de capa original do site da notícia"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
    except Exception as e:
        print(f"⚠️ Foto de capa original não encontrada: {e}")
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

    # 3. Geração do Roteiro na OpenAI API (com termos de busca estritamente concretos)
    print("🤖 Solicitando roteiro estruturado à OpenAI...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um roteirista documental de notícias. Com base no texto a seguir, crie um roteiro de 1.100 a 1.300 palavras (para um vídeo de 8 minutos).
    Divida o conteúdo em exatamente 8 blocos narrativos.

    REGRAS ESTRITAS PARA TERMOS DE BUSCA DE IMAGEM:
    - Para cada bloco, forneça uma lista de 6 a 8 termos de busca em português específicos e DIRETOS.
    - NUNCA use conceitos abstratos ou metafóricos (ex: NUNCA use "eficiência", "futuro", "energia", "sucesso", "tecnologia").
    - Use SOMENTE objetos físicos, locais reais, edifícios, máquinas ou figuras públicas (ex: "painel solar fotovoltaico", "usina hidrelétrica", "linha de transmissão elétrica", "ministro da fazenda brasil").
    - NUNCA inclua animais ou ilustrações a menos que a matéria seja especificamente sobre eles.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado para este trecho...",
          "termos_busca_imagens": [
            "termo concreto 1",
            "termo concreto 2",
            "termo concreto 3",
            "termo concreto 4",
            "termo concreto 5",
            "termo concreto 6"
          ]
        }}
      ]
    }}

    Notícia:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um gerador de roteiros jornalísticos extremamente focado em precisão visual concreta."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    roteiro = dados["roteiro"]
    print(f"✅ Roteiro gerado! Total de blocos: {len(roteiro)}")

    # 4. Processamento de Mídias Dinâmicas (Múltiplas imagens de ~7s por bloco)
    os.makedirs("output", exist_ok=True)
    concat_block_list = []

    for idx, bloco in enumerate(roteiro):
        print(f"\n🎬 Processando Bloco {idx + 1}/{len(roteiro)}...")
        
        audio_path = os.path.abspath(f"output/audio_{idx}.mp3")
        block_video_path = os.path.abspath(f"output/part_{idx}.mp4")

        # A. Gerar Voz com edge-tts
        cmd_tts = [
            "edge-tts",
            "--text", bloco["narracao"],
            "--voice", "pt-BR-AntonioNeural",
            "--write-media", audio_path
        ]
        subprocess.run(cmd_tts, check=True)

        # B. Calcular duração do áudio e quantidade de imagens (~7 segundos por imagem)
        duration = get_audio_duration(audio_path)
        num_images = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_images
        print(f"⏱️ Duração da narração: {duration:.1f}s | Gerando {num_images} imagens (~{sub_duration:.1f}s cada)")

        termos = bloco.get("termos_busca_imagens", ["noticia brasil"])
        sub_videos_list = []

        # C. Baixar e Renderizar Cada Imagem do Bloco
        for j in range(num_images):
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            
            termo = termos[j % len(termos)]
            imagem_salva = False

            # Primeira imagem do primeiro bloco usa a capa original da matéria se existir
            if idx == 0 and j == 0 and foto_capa_original:
                try:
                    res = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    imagem_salva = salvar_imagem_valida(res.content, img_path)
                except Exception:
                    imagem_salva = False

            if not imagem_salva:
                print(f"   🔎 Imagem {j+1}/{num_images} | Busca: '{termo}'")
                media_url = buscar_imagem_web(termo)
                try:
                    res = requests.get(media_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    imagem_salva = salvar_imagem_valida(res.content, img_path)
                except Exception:
                    imagem_salva = False

            if not imagem_salva:
                res = requests.get("https://picsum.photos/1920/1080", timeout=10)
                salvar_imagem_valida(res.content, img_path)

            # Efeito Zoom In / Zoom Out Alternado calculado para o tempo exato
            frames = int(sub_duration * 25)
            if (idx + j) % 2 == 0:
                zoom_filter = f"scale=2560:1440,zoompan=z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"
            else:
                zoom_filter = f"scale=2560:1440,zoompan=z='max(1.25-zoom*0.0015,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"

            cmd_sub_ffmpeg = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", img_path,
                "-t", str(sub_duration),
                "-vf", zoom_filter,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                sub_video_path
            ]
            subprocess.run(cmd_sub_ffmpeg, check=True)
            sub_videos_list.append(f"file '{sub_video_path}'")

        # D. Unir as sub-imagens do bloco e juntar com o Áudio
        sub_txt_path = os.path.abspath(f"output/sub_files_{idx}.txt")
        with open(sub_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(sub_videos_list))

        block_video_no_audio = os.path.abspath(f"output/no_audio_{idx}.mp4")
        cmd_join_sub = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", sub_txt_path, "-c", "copy", block_video_no_audio
        ]
        subprocess.run(cmd_join_sub, check=True)

        # Junta o vídeo das imagens com a narração em MP3
        cmd_merge_audio = [
            "ffmpeg", "-y",
            "-i", block_video_no_audio,
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", block_video_path
        ]
        subprocess.run(cmd_merge_audio, check=True)
        concat_block_list.append(f"file '{block_video_path}'")

    # 5. Concatenar Todos os 8 Blocos no Vídeo Final
    list_file_path = os.path.abspath("output/files.txt")
    final_video_path = os.path.abspath("final_video.mp4")

    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_block_list))

    print("\n🔄 Unindo todos os blocos no vídeo final de 8 minutos...")
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

    # 6. Enviar Arquivo Final para o Telegram via Pyrogram
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
