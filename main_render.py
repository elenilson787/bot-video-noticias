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
    """Gera imagem realista em 16:9 via Google Imagen 3 (Google AI Studio)"""
    if not gemini_key:
        return False
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt_enriquecido = (
        f"Award-winning photojournalism, documentary style, 8k resolution, cinematic lighting, {prompt_ingles}. "
        f"NO text, NO letters, NO words, NO logos."
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
            print(f"   ⚠️ Google Imagen retornou status {res.status_code} (filtro ativado).")
    except Exception as e:
        print(f"   ⚠️ Erro ao conectar no Google Imagen: {e}")
    return False

def gerar_imagem_ia_pollinations(prompt_ingles, target_path):
    """Gerador secundário de IA (FLUX Model) com semente aleatória para garantir imagens inéditas"""
    try:
        prompt_enriquecido = f"Photojournalism, cinematic documentary shot, 8k photo, {prompt_ingles}"
        prompt_encoded = urllib.parse.quote(prompt_enriquecido)
        seed = random.randint(10000, 999999)
        url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&seed={seed}&nologo=true&model=flux"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=25)
        if res.status_code == 200 and len(res.content) > 5000:
            return salvar_imagem_sem_distorcao(res.content, target_path)
    except Exception as e:
        print(f"   ⚠️ Erro no gerador IA secundário: {e}")
    return False

def buscar_pexels_photo_dinamico(prompt_ingles, pexels_key, target_path):
    """Backup dinâmico que busca fotos no Pexels usando palavras-chave da cena"""
    if not pexels_key:
        return False
    try:
        keywords = " ".join([word for word in prompt_ingles.split() if len(word) > 3][:3])
        headers = {"Authorization": pexels_key}
        url = f"https://api.pexels.com/v1/search?query={keywords}&per_page=10&orientation=landscape"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            photos = res.json().get("photos", [])
            if photos:
                photo = random.choice(photos)
                img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
                if img_url:
                    r = requests.get(img_url, timeout=8)
                    return salvar_imagem_sem_distorcao(r.content, target_path)
    except Exception:
        pass
    return False

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

    # 3. Análise da OpenAI
    print("🤖 Gerando roteiro pt-BR e descrições visuais de 10s...")
    client = OpenAI(api_key=openai_key)
    
    prompt_roteiro = f"""
    Você é um diretor de arte e roteirista de telejornalismo.
    
    SUA MISSÃO:
    1. Crie um roteiro narrado ESTRITAMENTE em PORTUGUÊS DO BRASIL (pt-BR) em 8 blocos narrativos.
    2. Para CADA BLOCO, forneça de 6 a 8 PROMPTS VISUAIS EXCLUSIVOS EM INGLÊS.
    3. Cada prompt visual servirá para gerar UMA IMAGEM ÚNICA DE IA a cada 10 SEGUNDOS de narração.

    REGRAS OBRIGATÓRIAS PARA OS PROMPTS DA IA (EM INGLÊS):
    - Crie descrições FOTOGRÁFICAS, SEGURAS E DOCUMENTAIS referentes ao assunto falado naquele exato trecho.
    - REGRAS DE SEGURANÇA (Para evitar o filtro da IA): NUNCA use palavras de violência explícita como "attack", "blood", "missile", "war", "explosion". Substitua por descrições diplomáticas ou territoriais seguras:
      * Em vez de explosão/ataque: "wide aerial photograph of a Mediterranean coastal city at sunset, hazy atmosphere, cinematic documentary style"
      * Em vez de política/discursos: "a formal press conference room with podium, microphones, blurred diplomatic flags background, soft lighting"
      * Em vez de reuniões: "diplomats sitting around a grand conference table in an international summit, wide shot photo"
    - PROIBIDO: NUNCA sugira letras, palavras escritas, placas, máquinas de escrever ou cartazes.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado exclusivamente em PORTUGUÊS DO BRASIL...",
          "prompts_ia_10s": [
            "Detailed safe visual prompt for 0-10s scene",
            "Detailed safe visual prompt for 10-20s scene",
            "Detailed safe visual prompt for 20-30s scene",
            "Detailed safe visual prompt for 30-40s scene",
            "Detailed safe visual prompt for 40-50s scene",
            "Detailed safe visual prompt for 50-60s scene"
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
            {"role": "system", "content": "Você é um diretor de arte especialista em prompts de imagem seguros para IA e sem filtros de bloqueio."},
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

        # B. Duração e cálculo exato de imagens (~10s cada)
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 10.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Narração pt-BR: {duration:.1f}s | Criando {num_segments} cenas com movimento de ~10s cada")

        prompts_cenas = bloco.get("prompts_ia_10s", [])
        sub_videos_list = []

        for j in range(num_segments):
            prompt_ia = prompts_cenas[j % len(prompts_cenas)] if prompts_cenas else "cinematic documentary scene photojournalism"
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            imagem_salva = False

            # 1. Google Imagen 3 (IA Principal)
            print(f"   🎨 Scene {scene_counter + 1}/{num_segments * len(roteiro)} | Gerando via Google Imagen 3...")
            imagem_salva = gerar_imagem_google_imagen(prompt_ia, gemini_key, img_path)

            # 2. Pollinations FLUX (IA Secundária - Fallback se o Google bloquear)
            if not imagem_salva:
                print(f"   ✨ Scene {scene_counter + 1}/{num_segments * len(roteiro)} | Gerando via IA Secundária (FLUX)...")
                imagem_salva = gerar_imagem_ia_pollinations(prompt_ia, img_path)

            # 3. Pexels Dinâmico
            if not imagem_salva:
                print(f"   📸 Scene {scene_counter + 1}/{num_segments * len(roteiro)} | Buscando foto documental alternativa...")
                imagem_salva = buscar_pexels_photo_dinamico(prompt_ia, pexels_key, img_path)

            # 4. Fallback visual seguro
            if not imagem_salva:
                img = Image.new('RGB', (1920, 1080), color=(15, 23, 42))
                img.save(img_path, 'JPEG', quality=95)

            scene_counter += 1

            # C. EDIÇÃO OBRIGATÓRIA DE MOVIMENTO EM 100% DAS IMAGENS
            frames = int(sub_duration * 25)
            if scene_counter % 2 == 0:
                # Efeito Zoom In (aproximação suave)
                zoom_filter = f"scale=2560:1440,zoompan=z='min(zoom+0.0012,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"
            else:
                # Efeito Zoom Out (afastamento suave)
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
    
