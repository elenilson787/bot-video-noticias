import os
import json
import math
import time
import base64
import random
import asyncio
import requests
import subprocess
from io import BytesIO
from PIL import Image, ImageOps
from openai import OpenAI
from pyrogram import Client
import trafilatura

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
    """Ajusta a imagem gerada em 16:9 (1920x1080) com máxima qualidade"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Erro ao formatar imagem: {e}")
        return False

def gerar_imagem_google_imagen(prompt_ingles, gemini_key, target_path):
    """Gera imagem realista em 16:9 via Google Imagen 3 com proibição estrita de textos/letras"""
    if not gemini_key:
        return False
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    
    # Prompt de alta qualidade com regras de exclusão visual de letrinhas/placas
    prompt_enriquecido = (
        f"Award-winning documentary photojournalism, 8k resolution, cinematic lighting, realistic detail, {prompt_ingles}. "
        f"NO text, NO written words, NO letters, NO scrabble blocks, NO signboards, NO posters, NO graphics."
    )
    
    payload = {
        "prompt": prompt_enriquecido,
        "config": {
            "numberOfImages": 1,
            "outputMimeType": "image/jpeg",
            "aspectRatio": "16:9"
        }
    }
    
    try:
        print(f"   🎨 [Google Imagen 3] Gerando cena: '{prompt_ingles[:50]}...'")
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            generated_images = data.get("generatedImages", [])
            if generated_images:
                base64_str = generated_images[0].get("image", {}).get("imageBytes")
                if base64_str:
                    img_bytes = base64.b64decode(base64_str)
                    return salvar_imagem_sem_distorcao(img_bytes, target_path)
        else:
            print(f"   ⚠️ Erro Google Imagen ({res.status_code}): {res.text[:120]}")
    except Exception as e:
        print(f"   ⚠️ Falha na conexão com Google Imagen: {e}")
    return False

def buscar_pexels_photo(termo, pexels_key):
    """Busca foto HD de backup na API Oficial do Pexels"""
    if not pexels_key:
        return None
    try:
        headers = {"Authorization": pexels_key}
        url = f"https://api.pexels.com/v1/search?query={termo}&per_page=6&orientation=landscape"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            photos = res.json().get("photos", [])
            if photos:
                photo = random.choice(photos)
                return photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
    except Exception:
        pass
    return None

async def main():
    # 1. Leitura de Variáveis de Ambiente
    news_url = os.getenv("NEWS_URL")
    chat_id = os.getenv("CHAT_ID")
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    pexels_key = os.getenv("PEXELS_API_KEY")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([news_url, chat_id, openai_key, telegram_token, telegram_api_id, telegram_api_hash]):
        raise ValueError("❌ Erro: Variáveis de ambiente obrigatórias não encontradas!")

    print(f"📥 Extraindo texto da notícia: {news_url}")

    # 2. Extração do Conteúdo da Notícia
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Análise da OpenAI com Instruções Estritas de Roteiro e Cenas Contextuais a cada 10s
    print("🤖 Gerando roteiro em Português (pt-BR) e ordens visuais de 10s para a IA...")
    client = OpenAI(api_key=openai_key)
    
    prompt_roteiro = f"""
    Você é um diretor de arte e roteirista de telejornalismo investigativo.
    
    SUA MISSÃO:
    1. Crie um roteiro narrado ESTRITAMENTE em PORTUGUÊS DO BRASIL (pt-BR) em 8 blocos narrativos.
    2. Para CADA BLOCO, forneça uma lista com a ORDEM LITERAL DE CRIAÇÃO DAS CENAS (prompts visuais em Inglês).
    3. Cada ordem visual deve corresponder a aproximadamente 10 SEGUNDOS de narração.

    REGRAS CRÍTICAS PARA OS PROMPTS VISUAIS (EM INGLÊS):
    - Crie descrições FOTOGRÁFICAS E REALISTAS do evento ou local sendo falado naquele exato momento.
    - Se a fala for sobre declarações políticas: "A realistic press conference room with podium, microphones, and blurred flags in the background, dramatic lighting"
    - Se a fala for sobre geografia/conflito: "Cinematic wide shot of a city skyline at sunset with dust clouds, atmospheric documentary style"
    - Se a fala for sobre diplomacia: "A wide shot of an international summit conference table with diplomats seated, realistic photo"
    - PROIBIDO ABSOLUTAMENTE: Letras de papel, blocos de madeira tipo Scrabble, textos escritos, palavras como 'VOTE' ou 'NEWS', máquinas de escrever ou gráficos conceituais.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado exclusivamente em PORTUGUÊS DO BRASIL...",
          "prompts_ia_10s": [
            "Detailed realistic English visual prompt for first 10s scene",
            "Detailed realistic English visual prompt for second 10s scene",
            "Detailed realistic English visual prompt for third 10s scene",
            "Detailed realistic English visual prompt for fourth 10s scene"
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
            {"role": "system", "content": "Você é um diretor de arte focado em gerar descrições de cenas fotojornalísticas realistas e sem textos em tela."},
            {"role": "user", "content": prompt_roteiro}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    roteiro = dados["roteiro"]

    # 4. Geração de Mídia e Renderização
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    scene_counter = 0

    for idx, bloco in enumerate(roteiro):
        print(f"\n🎬 Processando Bloco {idx + 1}/{len(roteiro)}...")
        
        audio_path = os.path.abspath(f"output/audio_{idx}.mp3")
        block_video_path = os.path.abspath(f"output/part_{idx}.mp4")

        # A. Gerar Voz pt-BR com edge-tts
        cmd_tts = [
            "edge-tts",
            "--text", bloco["narracao"],
            "--voice", "pt-BR-AntonioNeural",
            "--write-media", audio_path
        ]
        subprocess.run(cmd_tts, check=True)

        # B. Duração e cálculo exato de imagens a cada ~10 segundos de fala
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 10.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Narração pt-BR: {duration:.1f}s | Criando {num_segments} cenas exclusivas de ~10s cada")

        prompts_cenas = bloco.get("prompts_ia_10s", [])
        sub_videos_list = []

        for j in range(num_segments):
            prompt_ia = prompts_cenas[j % len(prompts_cenas)] if prompts_cenas else "cinematic documentary scene, photojournalism"
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            imagem_salva = False

            # 1. Tenta gerar a cena fotográfica via Google Imagen 3
            if gemini_key:
                imagem_salva = gerar_imagem_google_imagen(prompt_ia, gemini_key, img_path)

            # 2. Backup via Pexels se o Imagen falhar (com termos reais)
            if not imagem_salva and pexels_key:
                print(f"   📸 [Backup Pexels] Buscando foto documental...")
                img_url = buscar_pexels_photo("press conference diplomacy skyline", pexels_key)
                if img_url:
                    try:
                        res = requests.get(img_url, timeout=8)
                        imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                    except Exception:
                        pass

            # 3. Fallback visual seguro caso precise
            if not imagem_salva:
                img = Image.new('RGB', (1920, 1080), color=(15, 23, 42))
                img.save(img_path, 'JPEG', quality=95)

            scene_counter += 1

            # C. EDIÇÃO DE MOVIMENTO (Zoom In / Zoom Out Alternado)
            frames = int(sub_duration * 25)
            if scene_counter % 2 == 0:
                zoom_filter = f"scale=2560:1440,zoompan=z='min(zoom+0.0012,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"
            else:
                zoom_filter = f"scale=2560:1440,zoompan=z='max(1.20-zoom*0.0012,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"

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

        # D. Sincronizar sub-cenas do bloco com o áudio pt-BR
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
