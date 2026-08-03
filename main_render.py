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
from PIL import Image, ImageOps, ImageDraw
from openai import OpenAI
from pyrogram import Client
import trafilatura

# ==============================================================================
# CONFIGURAÇÃO
# False -> Gera imagens hiper-realistas por IA (Google Imagen 3 / FLUX)
# True  -> Modo de teste super rápido com slides locais
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
    """Ajusta a imagem gerada em 16:9 (1920x1080) com máxima qualidade"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Erro ao formatar imagem: {e}")
        return False

def criar_imagem_placeholder_teste(numero_cena, texto_trecho, target_path):
    """Cria um slide de teste 16:9 limpo para validação rápida"""
    try:
        cores = [(15, 23, 42), (30, 41, 59), (17, 24, 39), (24, 34, 56)]
        cor_fundo = cores[numero_cena % len(cores)]
        
        img = Image.new('RGB', (1920, 1080), color=cor_fundo)
        draw = ImageDraw.Draw(img)
        
        draw.rectangle([80, 80, 1840, 1000], outline=(51, 65, 85), width=4)
        draw.text((120, 120), f"MODO TESTE REALISTA - CENA #{numero_cena}", fill=(226, 232, 240))
        draw.text((120, 200), f"Prompt: {texto_trecho[:80]}...", fill=(148, 163, 184))
        
        img.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Erro ao criar placeholder local: {e}")
        return False

def gerar_imagem_google_imagen_realista(prompt_ingles, gemini_key, target_path):
    """Gera imagem no estilo fotojornalismo hiper-realista via Google Imagen 3"""
    if not gemini_key:
        return False
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt_enriquecido = (
        f"Award-winning documentary photojournalism, realistic news photograph, 8k resolution, cinematic lighting, {prompt_ingles}. "
        f"NO text, NO written words, NO letters, NO logos, NO 3D renders, NO cartoon, NO illustration."
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
                    print("   ✅ Sucesso via Google Imagen 3!")
                    return salvar_imagem_sem_distorcao(img_bytes, target_path)
        else:
            print(f"   ⚠️ Resposta Google Imagen: {res.status_code} - {res.text[:80]}")
    except Exception as e:
        print(f"   ⚠️ Erro de conexão Google Imagen: {e}")
    return False

def gerar_imagem_huggingface_realista(prompt_ingles, hf_token, target_path):
    """Gera imagem realista via Hugging Face API (FLUX.1-schnell)"""
    if not hf_token:
        return False
        
    url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}"}
    
    prompt_enriquecido = (
        f"Award-winning documentary photojournalism, realistic news picture, 8k resolution, cinematic lighting, {prompt_ingles}"
    )
    payload = {"inputs": prompt_enriquecido}
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200 and len(res.content) > 5000:
            print("   ✅ Sucesso via Hugging Face FLUX.1!")
            return salvar_imagem_sem_distorcao(res.content, target_path)
        elif res.status_code == 503:
            print("   ⏳ Modelo HF aquecendo na nuvem... aguardando 5s...")
            time.sleep(5)
    except Exception as e:
        print(f"   ⚠️ Erro Hugging Face: {e}")
    return False

def gerar_imagem_pollinations_flux_realista(prompt_ingles, target_path):
    """Gera imagem realista via Pollinations FLUX"""
    prompt_enriquecido = (
        f"Documentary photojournalism, realistic news picture, 8k resolution, cinematic lighting, {prompt_ingles}"
    )
    prompt_encoded = urllib.parse.quote(prompt_enriquecido)
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    for tentativa in range(3):
        try:
            time.sleep(3 * (tentativa + 1))  # Pausa preventiva anti-429
            seed = random.randint(100000, 999999)
            url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&seed={seed}&nologo=true&model=flux"
            
            res = session.get(url, timeout=30)
            if res.status_code == 200 and len(res.content) > 10000:
                print("   ✅ Sucesso via Pollinations FLUX!")
                return salvar_imagem_sem_distorcao(res.content, target_path)
            elif res.status_code == 429:
                print(f"   ⏳ Rate limit (429). Aguardando {5 * (tentativa + 1)}s...")
                time.sleep(5 * (tentativa + 1))
        except Exception as e:
            print(f"   ⚠️ Tentativa {tentativa+1} FLUX falhou: {e}")
            time.sleep(3)
            
    return False

def gerar_imagem_ia_garantida(prompt_ingles, gemini_key, hf_token, scene_num, target_path):
    """Gerenciador triplo de mídias de IA estilo Realista"""
    if MODO_TESTE:
        return criar_imagem_placeholder_teste(scene_num, prompt_ingles, target_path)

    # 1. Tenta Google Imagen 3
    if gemini_key:
        print(f"   🎨 Gerando cena Realista via Google Imagen 3...")
        if gerar_imagem_google_imagen_realista(prompt_ingles, gemini_key, target_path):
            return True

    # 2. Tenta Hugging Face FLUX.1
    if hf_token:
        print(f"   🤗 Gerando cena Realista via Hugging Face...")
        if gerar_imagem_huggingface_realista(prompt_ingles, hf_token, target_path):
            return True

    # 3. Tenta Pollinations FLUX
    print(f"   ✨ Gerando cena Realista via Pollinations FLUX...")
    if gerar_imagem_pollinations_flux_realista(prompt_ingles, target_path):
        return True

    # 4. Fallback de segurança local se todas as conexões esgotarem
    print(f"   🛡️ Gerando slide de segurança local...")
    return criar_imagem_placeholder_teste(scene_num, prompt_ingles, target_path)

async def main():
    # 1. Leitura de Variáveis de Ambiente
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

    print(f"📥 Extraindo texto da notícia: {news_url}")

    # 2. Extração da Notícia
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Análise da OpenAI
    print("🤖 Gerando roteiro pt-BR e prompts de imagem no estilo Fotojornalismo Realista...")
    client = OpenAI(api_key=openai_key)
    
    prompt_roteiro = f"""
    Você é um diretor de arte e roteirista de telejornalismo investigativo.
    
    SUA MISSÃO:
    1. Crie um roteiro narrado ESTRITAMENTE em PORTUGUÊS DO BRASIL (pt-BR) em 8 blocos narrativos.
    2. Para CADA BLOCO, forneça de 6 a 8 PROMPTS VISUAIS EXCLUSIVOS EM INGLÊS no estilo FOTOJORNALISMO REALISTA.
    3. Cada prompt visual servirá para gerar UMA IMAGEM ÚNICA DE IA a cada 10 SEGUNDOS de narração.

    REGRAS PARA OS PROMPTS VISUAIS (EM INGLÊS):
    - Crie descrições FOTOGRÁFICAS, SEGURAS E DOCUMENTAIS referentes ao que é falado naquele exato trecho.
    - REGRAS ANTI-BLOQUEIO DE SEGURANÇA: NUNCA use palavras de violência explícita ("attack", "blood", "war", "explosion", "missile"). Substitua por descrições diplomáticas, territoriais ou institucionais:
      * Em vez de guerra/ataque: "wide aerial photograph of a coastal city skyline at dusk, moody atmospheric lighting, documentary style"
      * Em vez de política/discursos: "a formal press conference room with podium, microphones, blurred flags in background, soft studio lighting"
      * Em vez de reuniões: "diplomats in suits sitting around an oval conference table in an international summit, wide shot"
    - PROIBIDO: NUNCA sugira letras, palavras escritas, placas, cartazes, 3D renders, animações ou ilustrações.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado exclusivamente em PORTUGUÊS DO BRASIL...",
          "prompts_ia_10s": [
            "Detailed realistic photo prompt for 0-10s scene",
            "Detailed realistic photo prompt for 10-20s scene"
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
            {"role": "system", "content": "Você é um diretor de arte especializado em prompts de imagem fotojornalísticos hiper-realistas."},
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

        # B. Duração e cálculo de imagens (~10s cada)
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 10.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Narração pt-BR: {duration:.1f}s | Criando {num_segments} cenas Realistas (~{sub_duration:.1f}s cada)")

        prompts_cenas = bloco.get("prompts_ia_10s", [])
        sub_videos_list = []

        for j in range(num_segments):
            prompt_ia = prompts_cenas[j % len(prompts_cenas)] if prompts_cenas else "documentary photojournalism, realistic news photo"
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            scene_counter += 1

            # Geração da imagem com triplo motor de IA estilo Realista
            gerar_imagem_ia_garantida(prompt_ia, gemini_key, hf_token, scene_counter, img_path)

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
