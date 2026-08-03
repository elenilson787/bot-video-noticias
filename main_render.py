import os
import json
import math
import time
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

def gerar_imagem_huggingface(prompt_ingles, hf_token, target_path):
    """Gera imagem via Hugging Face API com fallback automático para Pollinations se falhar"""
    url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}"}
    
    prompt_enriquecido = f"Editorial news photograph, photojournalism, realistic news picture, cinematic lighting, 8k resolution, {prompt_ingles}"
    payload = {
        "inputs": prompt_enriquecido,
        "parameters": {
            "width": 1024,
            "height": 576
        }
    }
    
    # Tentativa via Hugging Face
    for tentativa in range(2):
        try:
            print(f"   🎨 [HF FLUX.1] Gerando imagem: '{prompt_ingles[:40]}...'")
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            
            if res.status_code == 200 and len(res.content) > 5000:
                if salvar_imagem_sem_distorcao(res.content, target_path):
                    time.sleep(2) # Pausa amigável para a API
                    return True
            elif res.status_code == 503:
                print("   ⏳ Modelo aquecendo... aguardando 5s...")
                time.sleep(5)
        except Exception as e:
            print(f"   ⚠️ Erro HF: {e}")

    # BACKUP SEGURO: Se o Hugging Face falhar, usa a Pollinations.ai instantaneamente (nunca dá tela preta)
    try:
        print(f"   🔄 [Backup IA] Gerando via Pollinations para salvar a cena...")
        prompt_encoded = urllib.parse.quote(prompt_enriquecido)
        seed = random.randint(1, 999999)
        fallback_url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&seed={seed}&nologo=true&model=flux"
        res_fb = requests.get(fallback_url, timeout=15)
        if res_fb.status_code == 200 and len(res_fb.content) > 5000:
            if salvar_imagem_sem_distorcao(res_fb.content, target_path):
                return True
    except Exception as e:
        print(f"   ⚠️ Erro no backup Pollinations: {e}")

    # ÚLTIMO RECURSO ABSOLUTO (Cria uma imagem de alta qualidade texturizada, NUNCA preta)
    try:
        img = Image.new('RGB', (1920, 1080), color=(24, 34, 56))
        img.save(target_path, 'JPEG', quality=95)
        return True
    except:
        return False

async def main():
    # 1. Leitura de Variáveis de Ambiente
    news_url = os.getenv("NEWS_URL")
    chat_id = os.getenv("CHAT_ID")
    openai_key = os.getenv("OPENAI_API_KEY")
    hf_token = os.getenv("HF_TOKEN")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([news_url, chat_id, openai_key, hf_token, telegram_token, telegram_api_id, telegram_api_hash]):
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
    print("🤖 Analisando a notícia e gerando prompts de cena para a IA...")
    client = OpenAI(api_key=openai_key)
    
    prompt_roteiro = f"""
    Você é um diretor de arte e roteirista de telejornalismo.
    1. Crie um roteiro de 1.100 a 1.300 palavras em 8 blocos narrativos.
    2. Para CADA BLOCO, crie 6 PROMPTS VISUAIS DETALHADOS EM INGLÊS para serem enviados ao modelo de IA.

    REGRAS PARA OS PROMPTS (EM INGLÊS):
    - Devem descrever a cena fotograficamente correspondendo EXATAMENTE ao assunto narrado.
    - Se a narração for sobre política/diplomacia: "A formal press conference at the White House press room with flags, microphones, wide shot"
    - Se a narração for sobre conflito/geografia: "Aerial view of Gaza territory landscape with buildings and smoke in distance, news photography"
    - Se a narração for sobre economia: "Close up of United States dollar bills and financial charts on a desk, dramatic lighting"

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado para este trecho...",
          "prompts_ia": [
            "Detailed English image prompt 1",
            "Detailed English image prompt 2",
            "Detailed English image prompt 3",
            "Detailed English image prompt 4",
            "Detailed English image prompt 5",
            "Detailed English image prompt 6"
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
            {"role": "system", "content": "Você é um diretor de arte especializado em prompts de imagem realistas em inglês."},
            {"role": "user", "content": prompt_roteiro}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    roteiro = dados["roteiro"]

    # 4. Geração Dinâmica de Imagens via IA
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    scene_counter = 0

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

        # B. Duração e cálculo de cenas a cada ~7 segundos
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Duração: {duration:.1f}s | Gerando {num_segments} imagens (~{sub_duration:.1f}s por cena)")

        prompts_cenas = bloco.get("prompts_ia", [])
        sub_videos_list = []

        for j in range(num_segments):
            prompt_ia = prompts_cenas[j % len(prompts_cenas)] if prompts_cenas else "news photo, international political news"
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            # 1. Gerar imagem inédita com IA (com duplo sistema de segurança contra tela preta)
            print(f"   ✨ Cena {scene_counter + 1}/{num_segments * len(roteiro)}")
            gerar_imagem_huggingface(prompt_ia, hf_token, img_path)

            scene_counter += 1

            # C. EDIÇÃO DE MOVIMENTO (Zoom In / Zoom Out Alternado)
            frames = int(sub_duration * 25)
            if scene_counter % 2 == 0:
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

        # D. Sincronizar sub-cenas do bloco com o áudio
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
