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

def validar_e_converter_imagem(binary_content):
    """Valida a imagem e garante resolução mínima adequada"""
    try:
        img = Image.open(BytesIO(binary_content))
        img = img.convert('RGB')
        width, height = img.size
        if width < 300 or height < 200: # Ignora ícones/imagens muito pequenas
            return None
        output = BytesIO()
        img.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception:
        return None

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

def montar_pool_de_imagens(tema_principal, termos_busca, foto_capa_bytes):
    """Faz busca em lote no início para criar um pool diversificado de fotos do tema"""
    pool = []

    # 1. Adiciona a foto de capa oficial como primeira imagem
    if foto_capa_bytes:
        img_valid = validar_e_converter_imagem(foto_capa_bytes)
        if img_valid:
            pool.append(img_valid)

    # 2. Monta as consultas de busca jornalística
    queries = [
        tema_principal,
        f"{tema_principal} jogo futebol",
        f"{tema_principal} noticia"
    ]
    for t in termos_busca:
        if t and t not in queries:
            queries.append(f"{tema_principal} {t}")

    print(f"🔎 Coletando pool de imagens reais para o tema: [{tema_principal}]...")
    ddgs = DDGS()
    
    for q in queries[:5]: # Executa no máximo 5 consultas para evitar bloqueios
        try:
            results = ddgs.images(keywords=f"{q} foto", max_results=8)
            if results:
                for item in results:
                    url = item.get("image")
                    if url and url.startswith("http"):
                        try:
                            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
                            if res.status_code == 200:
                                valid_bytes = validar_e_converter_imagem(res.content)
                                if valid_bytes and valid_bytes not in pool:
                                    pool.append(valid_bytes)
                                    print(f"   ✅ Foto capturada ({len(pool)} no pool)")
                                    if len(pool) >= 30:
                                        break
                        except Exception:
                            continue
            if len(pool) >= 30:
                break
        except Exception as e:
            print(f"⚠️ Aviso na consulta '{q}': {e}")

    print(f"📸 Pool finalizado com {len(pool)} imagens reais e validadas!")
    return pool

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
    
    # Baixar capa original se existir
    foto_capa_url = extrair_foto_capa_noticia(news_url)
    foto_capa_bytes = None
    if foto_capa_url:
        try:
            res_capa = requests.get(foto_capa_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if res_capa.status_code == 200:
                foto_capa_bytes = res_capa.content
        except Exception:
            pass

    # 2. Extração do texto
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Geração do Roteiro e Termos de Busca na OpenAI
    print("🤖 Analisando conteúdo da notícia com a OpenAI...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um editor executivo de telejornalismo. Analise o texto da notícia e:
    1. Identifique o TEMA CENTRAL e ENTIDADES PRINCIPAIS em até 4 palavras (ex: "Racismo jogo Paulista Sub 15 arbitro Marcos").
    2. Crie 4 termos de busca adicionais diretamente relacionados ao contexto da matéria.
    3. Crie um roteiro completo de 1.100 a 1.300 palavras (para um vídeo de 8 minutos) dividido em exatamente 8 blocos narrativos.

    Retorne ESTRITAMENTE um JSON no seguinte formato:
    {{
      "tema_principal": "Tema central curto aqui",
      "termos_busca": ["termo 1", "termo 2", "termo 3", "termo 4"],
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado para este trecho..."
        }}
      ]
    }}

    Notícia:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um gerador de roteiros jornalísticos focado em precisão contextual."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    tema_principal = dados.get("tema_principal", "Notícias Brasil")
    termos_busca = dados.get("termos_busca", [])
    roteiro = dados["roteiro"]

    # 4. Monta o Pool de Imagens
    pool_imagens = montar_pool_de_imagens(tema_principal, termos_busca, foto_capa_bytes)
    
    if not pool_imagens:
        # Fallback de emergência caso todas as buscas falhem
        res_fall = requests.get("https://images.unsplash.com/photo-1541872703-74c5e44368f9?w=1200", timeout=10)
        pool_imagens.append(validar_e_converter_imagem(res_fall.content))

    # 5. Processamento dos Blocos com Alternância Cíclica de Imagens
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    global_img_index = 0

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

        # B. Calcular duração e quantidade de imagens (~7s cada)
        duration = get_audio_duration(audio_path)
        num_images = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_images
        print(f"⏱️ Duração: {duration:.1f}s | Montando {num_images} segmentos de ~{sub_duration:.1f}s")

        sub_videos_list = []

        for j in range(num_images):
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")

            # Seleciona a próxima imagem do pool em formato circular
            img_bytes = pool_imagens[global_img_index % len(pool_imagens)]
            global_img_index += 1

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            # Efeito Zoom In / Zoom Out Alternado
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

        # C. Unir sub-imagens do bloco e juntar com áudio
        sub_txt_path = os.path.abspath(f"output/sub_files_{idx}.txt")
        with open(sub_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(sub_videos_list))

        block_video_no_audio = os.path.abspath(f"output/no_audio_{idx}.mp4")
        cmd_join_sub = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", sub_txt_path, "-c", "copy", block_video_no_audio
        ]
        subprocess.run(cmd_join_sub, check=True)

        cmd_merge_audio = [
            "ffmpeg", "-y",
            "-i", block_video_no_audio,
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", block_video_path
        ]
        subprocess.run(cmd_merge_audio, check=True)
        concat_block_list.append(f"file '{block_video_path}'")

    # 6. Concatenar Blocos no Vídeo Final
    list_file_path = os.path.abspath("output/files.txt")
    final_video_path = os.path.abspath("final_video.mp4")

    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_block_list))

    print("\n🔄 Unindo blocos no vídeo final...")
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

    # 7. Enviar para o Telegram via Pyrogram
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
