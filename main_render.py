import os
import json
import math
import time
import base64
import random
import urllib.parse
import asyncio
import requests
import subprocess
from io import BytesIO
from PIL import Image, ImageOps, ImageEnhance
from openai import OpenAI
from pyrogram import Client
import trafilatura

# Importação segura da biblioteca de busca
try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

# ==============================================================================
# CONFIGURAÇÃO DE PRODUÇÃO
MODO_TESTE = False
# ==============================================================================

def get_media_duration(file_path):
    """Retorna a duração exata do áudio em segundos"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def salvar_imagem_sem_distorcao(binary_content, target_path):
    """Ajusta a imagem para 16:9 Widescreen (1920x1080) em qualidade máxima"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        
        # Realce de contraste e nitidez para estética cinematográfica
        enhancer = ImageEnhance.Contrast(img_fitted)
        img_fitted = enhancer.enhance(1.05)
        
        img_fitted.save(target_path, 'JPEG', quality=98)
        return True
    except Exception as e:
        print(f"⚠️ Erro ao formatar imagem: {e}")
        return False

# ------------------------------------------------------------------------------
# MOTOR DE MÍDIA - CASCATA DE 4 NÍVEIS
# ------------------------------------------------------------------------------

def N1_gerar_google_imagen(prompt_ingles, gemini_key, target_path):
    """Nível 1: Google Imagen 3"""
    if not gemini_key:
        return False
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt_enriquecido = (
        f"Award-winning documentary photojournalism, shot on 35mm lens, 8k resolution, cinematic lighting, {prompt_ingles}. "
        f"NO text, NO letters, NO words, NO logos, NO 3D renders, NO cartoon, NO illustration."
    )
    
    payload = {
        "prompt": prompt_enriquecido,
        "config": {
            "numberOfImages": 1,
            "aspectRatio": "16:9",
            "outputMimeType": "image/jpeg"
        }
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            generated_images = data.get("generatedImages", [])
            if generated_images:
                base64_str = generated_images[0].get("image", {}).get("imageBytes")
                if base64_str:
                    img_bytes = base64.b64decode(base64_str)
                    print("   ✅ [Nível 1] Imagem gerada via Google Imagen 3!")
                    return salvar_imagem_sem_distorcao(img_bytes, target_path)
    except Exception as e:
        print(f"   ⚠️ [N1] Imagen 3 indisponível: {e}")
    return False

def N2_gerar_huggingface(prompt_ingles, hf_token, target_path):
    """Nível 2: Hugging Face (FLUX.1-schnell)"""
    if not hf_token:
        return False
        
    url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}"}
    prompt_enriquecido = f"Award-winning documentary photojournalism, realistic news picture, 8k resolution, cinematic, {prompt_ingles}"
    
    try:
        res = requests.post(url, headers=headers, json={"inputs": prompt_enriquecido}, timeout=25)
        if res.status_code == 200 and len(res.content) > 5000:
            print("   ✅ [Nível 2] Imagem gerada via Hugging Face FLUX.1!")
            return salvar_imagem_sem_distorcao(res.content, target_path)
    except Exception as e:
        print(f"   ⚠️ [N2] Hugging Face indisponível: {e}")
    return False

def N3_gerar_pollinations(prompt_ingles, target_path):
    """Nível 3: Pollinations FLUX com taxa controlada"""
    prompt_enriquecido = f"Documentary photojournalism, realistic news picture, 8k resolution, cinematic lighting, {prompt_ingles}"
    prompt_encoded = urllib.parse.quote(prompt_enriquecido)
    
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    for tentativa in range(2):
        try:
            time.sleep(3)
            seed = random.randint(100000, 999999)
            url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&seed={seed}&nologo=true&model=flux"
            res = session.get(url, timeout=25)
            if res.status_code == 200 and len(res.content) > 10000:
                print("   ✅ [Nível 3] Imagem gerada via Pollinations FLUX!")
                return salvar_imagem_sem_distorcao(res.content, target_path)
        except Exception:
            time.sleep(2)
    return False

def N4_buscar_foto_noticia_real(query_especifico, target_path):
    """Nível 4: Busca de Fotos Jornalísticas Reais em HD (DDGS ou Wikimedia Fallback)"""
    print(f"   🔎 [Nível 4] Buscando foto real de notícia para: '{query_especifico}'...")
    
    # Tentativa via DDGS (se disponível)
    if DDGS is not None:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query_especifico, max_results=8))
                random.shuffle(results)
                
                for r in results:
                    img_url = r.get('image')
                    if img_url and any(ext in img_url.lower() for ext in ['.jpg', '.jpeg', '.png']):
                        try:
                            res = requests.get(img_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                            if res.status_code == 200 and len(res.content) > 15000:
                                if salvar_imagem_sem_distorcao(res.content, target_path):
                                    print("   ✅ [Nível 4] Foto real de alta definição capturada via DDGS!")
                                    return True
                        except Exception:
                            continue
        except Exception as e:
            print(f"   ⚠️ [N4] DDGS instável: {e}")

    # Fallback via Wikimedia Commons API (100% nativo e sem dependência externa)
    try:
        url_wiki = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(query_especifico)}&gsrlimit=6&prop=pageimages&piprop=original&format=json"
        res = requests.get(url_wiki, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if res.status_code == 200:
            pages = res.json().get('query', {}).get('pages', {})
            for page_id, page_info in pages.items():
                img_src = page_info.get('original', {}).get('source')
                if img_src and any(ext in img_src.lower() for ext in ['.jpg', '.jpeg', '.png']):
                    r_img = requests.get(img_src, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                    if r_img.status_code == 200 and len(r_img.content) > 15000:
                        if salvar_imagem_sem_distorcao(r_img.content, target_path):
                            print("   ✅ [Nível 4] Foto real capturada via Wikimedia!")
                            return True
    except Exception as e:
        print(f"   ⚠️ [N4] Wikimedia indisponível: {e}")

    return False

def adquirir_imagem_cinematografica(prompt_ia, query_real, gemini_key, hf_token, target_path):
    """Gerenciador garantido em cascata"""
    time.sleep(1.5)
    
    # 1. Google Imagen 3
    if N1_gerar_google_imagen(prompt_ia, gemini_key, target_path):
        return True

    # 2. Hugging Face FLUX.1
    if N2_gerar_huggingface(prompt_ia, hf_token, target_path):
        return True

    # 3. Pollinations FLUX
    if N3_gerar_pollinations(prompt_ia, target_path):
        return True

    # 4. Busca Foto Real Específica
    if N4_buscar_foto_noticia_real(query_real, target_path):
        return True

    # Fallback com termo jornalístico genérico
    return N4_buscar_foto_noticia_real("press conference news room photo", target_path)

# ------------------------------------------------------------------------------
# PROCESSAMENTO PRINCIPAL
# ------------------------------------------------------------------------------

async def main():
    news_url = os.getenv("NEWS_URL")
    chat_id = os.getenv("CHAT_ID")
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    hf_token = os.getenv("HF_TOKEN")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([news_url, chat_id, openai_key, telegram_token, telegram_api_id, telegram_api_hash]):
        raise ValueError("❌ Erro: Variáveis de ambiente obrigatórias não encontradas!")

    print(f"📥 Extraindo conteúdo da notícia: {news_url}")

    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto da notícia.")

    print("🤖 Direção de Arte & Roteiro Cinematográfico em Português...")
    client = OpenAI(api_key=openai_key)
    
    prompt_roteiro = f"""
    Você é um diretor de arte e roteirista sênior de documentários internacionais.
    
    SUA MISSÃO:
    1. Crie uma narração em PORTUGUÊS DO BRASIL (PT-BR) jornalística e envolvente dividida em 8 blocos.
    2. Para CADA BLOCO, forneça de 6 a 8 pares de termos visuais para cada janela de 10 SEGUNDOS de fala:
       - "prompt_ia": Descrição fotojornalística cinematográfica em Inglês (sem texto, sem letras, sem logos, estilo filme 35mm).
       - "query_real": Termo de busca em Inglês focado nas Pessoas, Locais ou Instituições REAIS mencionadas na narração (ex: "Donald Trump Oval Office press photo", "Gaza territory aerial view", "White House briefing room").

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado exclusivamente em PORTUGUÊS DO BRASIL...",
          "cenas": [
            {{
              "prompt_ia": "Cinematic photojournalism prompt for AI...",
              "query_real": "Specific real entity news photo query..."
            }}
          ]
        }}
      ]
    }}

    Notícia Original:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um diretor de arte fotojornalístico especialista em mídias de documentário."},
            {"role": "user", "content": prompt_roteiro}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    roteiro = dados["roteiro"]

    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    scene_counter = 0

    for idx, bloco in enumerate(roteiro):
        print(f"\n🎬 Processando Bloco {idx + 1}/{len(roteiro)}...")
        
        audio_path = os.path.abspath(f"output/audio_{idx}.mp3")
        block_video_path = os.path.abspath(f"output/part_{idx}.mp4")

        # Narração PT-BR com edge-tts
        cmd_tts = [
            "edge-tts",
            "--text", bloco["narracao"],
            "--voice", "pt-BR-AntonioNeural",
            "--write-media", audio_path
        ]
        subprocess.run(cmd_tts, check=True)

        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 10.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Narração: {duration:.1f}s | Gerando {num_segments} tomadas cinematográficas (~{sub_duration:.1f}s cada)")

        cenas_bloco = bloco.get("cenas", [])
        sub_videos_list = []

        for j in range(num_segments):
            cena_data = cenas_bloco[j % len(cenas_bloco)] if cenas_bloco else {}
            prompt_ia = cena_data.get("prompt_ia", "documentary photojournalism, realistic news photo")
            query_real = cena_data.get("query_real", "international news press photo")

            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            scene_counter += 1

            # Aquisição garantida da imagem
            print(f"   🖼️ Tomada {scene_counter}/{num_segments * len(roteiro)}")
            adquirir_imagem_cinematografica(prompt_ia, query_real, gemini_key, hf_token, img_path)

            # EDIÇÃO CINEMATOGRÁFICA (Color Grading + 4 Movimentos Variados)
            frames = int(sub_duration * 25)
            tipo_movimento = scene_counter % 4

            if tipo_movimento == 0:
                vf_filter = f"scale=2560:1440,zoompan=z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,eq=contrast=1.08:saturation=1.12,fps=25"
            elif tipo_movimento == 1:
                vf_filter = f"scale=2560:1440,zoompan=z='max(1.25-zoom*0.0015,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,eq=contrast=1.08:saturation=1.12,fps=25"
            elif tipo_movimento == 2:
                vf_filter = f"scale=2560:1440,zoompan=z=1.15:x='if(eq(on,1),iw/4,(x-1.2))':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,eq=contrast=1.08:saturation=1.12,fps=25"
            else:
                vf_filter = f"scale=2560:1440,zoompan=z=1.15:x='if(eq(on,1),0,(x+1.2))':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,eq=contrast=1.08:saturation=1.12,fps=25"

            cmd_sub_ffmpeg = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", img_path,
                "-t", str(sub_duration),
                "-vf", vf_filter,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                sub_video_path
            ]
            subprocess.run(cmd_sub_ffmpeg, check=True)
            sub_videos_list.append(f"file '{sub_video_path}'")

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

    # União final
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
