import os
import json
import math
import asyncio
import requests
import subprocess
from io import BytesIO
from PIL import Image, ImageOps
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import OpenAI
from pyrogram import Client
import trafilatura

def get_media_duration(file_path):
    """Retorna a duração exata de um áudio ou vídeo em segundos"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def salvar_imagem_sem_distorcao(binary_content, target_path):
    """Corta e ajusta a imagem em 16:9 (1920x1080) SEM ESTICAR ou deformar"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Imagem descartada: {e}")
        return False

def buscar_wikimedia_commons(termo):
    """Busca fotos reais no Wikimedia Commons (Imune a bloqueios)"""
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{termo}",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json"
        }
        headers = {'User-Agent': 'BotNoticias/1.0 (https://github.com)'}
        res = requests.get(url, params=params, headers=headers, timeout=6)
        data = res.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            imageinfo = page_info.get("imageinfo", [])
            if imageinfo:
                img_url = imageinfo[0].get("url")
                if img_url and any(img_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                    return img_url
    except Exception as e:
        print(f"⚠️ Wikimedia search error: {e}")
    return None

def buscar_imagem_ddg(termo, tema_principal):
    """Busca imagens no DuckDuckGo"""
    query_composta = f"{tema_principal} {termo} foto noticia"
    try:
        results = DDGS().images(keywords=query_composta, max_results=3)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception:
        pass
    return None

def baixar_clip_youtube(termo_busca, output_path):
    """Tenta baixar 5 segundos de vídeo real do YouTube"""
    try:
        print(f"   🎬 [TURNO DE VÍDEO] Baixando clipe do YouTube: '{termo_busca}'...")
        cmd = [
            "yt-dlp",
            f"ytsearch1:{termo_busca} noticias",
            "--download-sections", "*0-5",
            "-f", "bestvideo[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "-o", output_path,
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--no-playlist",
            "--quiet",
            "--no-warnings"
        ]
        subprocess.run(cmd, check=True, timeout=22)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
            return True
    except Exception as e:
        print(f"   ⚠️ YouTube indisponível para '{termo_busca}': {e}")
    return False

def extrair_foto_capa_noticia(url):
    """Extrai a foto de capa original do site da notícia"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
    except Exception:
        pass
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

    # 2. Extração do Conteúdo
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Geração do Roteiro e Termos de Busca
    print("🤖 Analisando a notícia e definindo cenas...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um diretor de edição de documentários de notícias.
    1. Identifique o TEMA CENTRAL e PERSONAGENS PRINCIPAIS da matéria.
    2. Crie um roteiro de 1.100 a 1.300 palavras (para um vídeo de 8 minutos) em 8 blocos narrativos.
    3. Para cada bloco, crie 6 termos de busca variados em português/inglês referentes a locais, pessoas ou conceitos reais (ex: "Gaza", "White House press conference", "Donald Trump speech", "United Nations flag", "Middle East map").

    Retorne ESTRITAMENTE um JSON no seguinte formato:
    {{
      "tema_principal": "Tema central curto",
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado...",
          "termos_busca": [
            "termo 1",
            "termo 2",
            "termo 3",
            "termo 4",
            "termo 5",
            "termo 6"
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
            {"role": "system", "content": "Você é um gerador de roteiros focado em diversidade visual concreta."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    tema_principal = dados.get("tema_principal", "Notícias")
    roteiro = dados["roteiro"]
    print(f"🎯 Tema Central: [{tema_principal}]")

    # 4. Processamento dos Blocos com Alternância Rigorosa (IMAGEM -> VÍDEO -> IMAGEM -> VÍDEO)
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    pool_mids = []
    
    # Contador Global de Cenas para intercalar perfeitamente no vídeo todo
    global_scene_counter = 0 

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

        # B. Duração e cálculo de segmentos (~6 segundos cada)
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 6.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Duração: {duration:.1f}s | Montando {num_segments} cenas")

        termos = bloco.get("termos_busca", [tema_principal])
        sub_videos_list = []

        for j in range(num_segments):
            termo = termos[j % len(termos)]
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            raw_video_path = os.path.abspath(f"output/raw_yt_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            # Verifica o turno: Par = IMAGEM | Ímpar = VÍDEO
            eh_turno_de_video = (global_scene_counter % 2 == 1)
            global_scene_counter += 1

            usou_video = False

            if eh_turno_de_video:
                usou_video = baixar_clip_youtube(f"{tema_principal} {termo}", raw_video_path)
                if usou_video:
                    cmd_ffmpeg_vid = [
                        "ffmpeg", "-y",
                        "-i", raw_video_path,
                        "-t", str(sub_duration),
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=25",
                        "-an",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        sub_video_path
                    ]
                    try:
                        subprocess.run(cmd_ffmpeg_vid, check=True)
                    except Exception:
                        usou_video = False

            # Se for turno de IMAGEM (ou se o vídeo falhou), baixa e renderiza foto com Zoom
            if not usou_video:
                imagem_salva = False

                # 1. Foto de capa na 1ª cena
                if idx == 0 and j == 0 and foto_capa_original:
                    try:
                        res = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                        imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                    except Exception:
                        imagem_salva = False

                # 2. Busca no DuckDuckGo
                if not imagem_salva:
                    print(f"   📸 [TURNO DE IMAGEM] Buscando foto (DuckDuckGo): '{termo}'")
                    media_url = buscar_imagem_ddg(termo, tema_principal)
                    if media_url:
                        try:
                            res = requests.get(media_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                            imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                            if imagem_salva:
                                pool_mids.append(res.content)
                        except Exception:
                            imagem_salva = False

                # 3. Busca no Wikimedia Commons
                if not imagem_salva:
                    print(f"   🏛️ [TURNO DE IMAGEM] Buscando foto (Wikimedia): '{termo}'")
                    media_url = buscar_wikimedia_commons(f"{termo}")
                    if media_url:
                        try:
                            res = requests.get(media_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                            imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                            if imagem_salva:
                                pool_mids.append(res.content)
                        except Exception:
                            imagem_salva = False

                # 4. Fallback Rotativo do Pool
                if not imagem_salva:
                    print("   ⚠️ Usando imagem do pool de variação.")
                    if pool_mids:
                        img_backup = pool_mids[(idx + j) % len(pool_mids)]
                        salvar_imagem_sem_distorcao(img_backup, img_path)
                    else:
                        res = requests.get("https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1200", timeout=10)
                        salvar_imagem_sem_distorcao(res.content, img_path)

                # Renderiza Foto com Efeito Zoom In/Out
                frames = int(sub_duration * 25)
                if (global_scene_counter) % 2 == 0:
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

        # C. Unir sub-cenas do bloco e juntar com áudio
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

    # 5. Concatenar Todos os Blocos no Vídeo Final
    list_file_path = os.path.abspath("output/files.txt")
    final_video_path = os.path.abspath("final_video.mp4")

    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_block_list))

    print("\n🔄 Unindo todos os blocos no vídeo final...")
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
