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

def buscar_imagem_web(termo_especifico, tema_principal):
    """Busca mídias reais ancoradas obrigatoriamente no TEMA PRINCIPAL da notícia"""
    query_composta = f"{tema_principal} {termo_especifico} foto noticia"
    try:
        results = DDGS().images(keywords=query_composta, max_results=5)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception as e:
        print(f"⚠️ Erro ao buscar imagem para '{query_composta}': {e}")
    
    # Segunda tentativa: busca apenas pelo Tema Principal da notícia
    try:
        results = DDGS().images(keywords=f"{tema_principal} foto noticia brasil", max_results=5)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception:
        pass

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

    # 3. Geração do Roteiro na OpenAI API (com Ancoragem de Tema Global)
    print("🤖 Analisando conteúdo da notícia e identificando o TEMA CENTRAL...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um editor executivo de telejornalismo. Leia o texto da notícia e:
    1. Identifique o TEMA CENTRAL e as ENTIDADES PRINCIPAIS da matéria em até 4 palavras (ex: "Lula convenção PT eleições", "Mercado financeiro alta dólar", "Guerra Ucrânia conflito").
    2. Crie um roteiro de 1.100 a 1.300 palavras (para um vídeo de 8 minutos) dividido em 8 blocos narrativos.
    3. Para cada bloco, forneça uma lista de 6 a 8 sub-termos de busca em português referentes ao trecho narrado.

    REGRA DE OURO PARA IMAGENS:
    - NUNCA use termos genéricos como "idosos", "educação", "tecnologia", "dinheiro" isoladamente.
    - Todos os sub-termos devem se referir DIRETAMENTE ao contexto do assunto ou personagens da notícia.

    Retorne ESTRITAMENTE um JSON no seguinte formato:
    {{
      "tema_principal": "ENTIDADES E TEMA CENTRAL AQUI",
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto longo narrado para este trecho...",
          "termos_busca_imagens": [
            "subtermo 1",
            "subtermo 2",
            "subtermo 3",
            "subtermo 4",
            "subtermo 5",
            "subtermo 6"
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
            {"role": "system", "content": "Você é um gerador de roteiros jornalísticos focado em precisão contextual rigorosa."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    tema_principal = dados.get("tema_principal", "Notícias Brasil")
    roteiro = dados["roteiro"]
    print(f"🎯 Tema Central Identificado pela IA: [{tema_principal}]")
    print(f"✅ Roteiro gerado! Total de blocos: {len(roteiro)}")

    # 4. Processamento das Mídias com Fallback Inteligente
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    ultima_imagem_valida_bytes = None

    # Baixar a capa original como primeiro backup oficial
    if foto_capa_original:
        try:
            res_capa = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if res_capa.status_code == 200:
                ultima_imagem_valida_bytes = res_capa.content
        except Exception:
            pass

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

        # B. Duração e divisão de imagens (~7s por imagem)
        duration = get_audio_duration(audio_path)
        num_images = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_images
        print(f"⏱️ Duração: {duration:.1f}s | Processando {num_images} imagens ancoradas ao tema...")

        termos = bloco.get("termos_busca_imagens", [tema_principal])
        sub_videos_list = []

        for j in range(num_images):
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            
            termo = termos[j % len(termos)]
            imagem_salva = False

            # Primeira imagem do primeiro bloco usa a capa oficial da matéria
            if idx == 0 and j == 0 and ultima_imagem_valida_bytes:
                imagem_salva = salvar_imagem_valida(ultima_imagem_valida_bytes, img_path)

            if not imagem_salva:
                print(f"   🔎 Imagem {j+1}/{num_images} | Busca: [{tema_principal}] + [{termo}]")
                media_url = buscar_imagem_web(termo, tema_principal)
                if media_url:
                    try:
                        res = requests.get(media_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if res.status_code == 200:
                            imagem_salva = salvar_imagem_valida(res.content, img_path)
                            if imagem_salva:
                                ultima_imagem_valida_bytes = res.content # Atualiza backup
                    except Exception:
                        imagem_salva = False

            # FALLBACK DE SEGURANÇA SEM PICSUM: Reutiliza a última imagem válida da notícia
            if not imagem_salva:
                print("   ⚠️ Busca externa falhou. Reutilizando foto contextual válida anterior...")
                if ultima_imagem_valida_bytes:
                    salvar_imagem_valida(ultima_imagem_valida_bytes, img_path)
                else:
                    # Caso extremo onde nem a foto de capa baixou
                    res = requests.get("https://images.unsplash.com/photo-1541872703-74c5e44368f9?w=1200", timeout=10)
                    salvar_imagem_valida(res.content, img_path)

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

        # C. Unir sub-imagens e sincronizar com áudio
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

    # 5. Concatenar Blocos no Vídeo Final
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
