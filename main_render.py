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
    """Ajusta a foto no enquadramento 16:9 (1920x1080) SEM esticar o rosto da pessoa"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Imagem inválida descartada: {e}")
        return False

def buscar_wikimedia_commons(nome_pessoa):
    """Busca fotos oficiais de figuras públicas no Wikimedia Commons (API pública imune a bloqueios)"""
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{nome_pessoa}",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json"
        }
        headers = {'User-Agent': 'BotNoticias/1.0 (https://github.com)'}
        res = requests.get(url, params=params, headers=headers, timeout=6)
        pages = res.json().get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            imageinfo = page_info.get("imageinfo", [])
            if imageinfo:
                img_url = imageinfo[0].get("url")
                if img_url and any(img_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                    return img_url
    except Exception:
        pass
    return None

def buscar_imagem_ddg(nome_pessoa):
    """Busca fotos jornalísticas de figuras públicas no DuckDuckGo"""
    try:
        results = DDGS().images(keywords=f"{nome_pessoa} foto noticia", max_results=3)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception:
        pass
    return None

def extrair_foto_capa_noticia(url):
    """Extrai a foto de capa original do artigo da notícia"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
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

    # 2. Extração da Notícia
    downloaded = trafilatura.fetch_url(news_url)
    if not downloaded:
        raise Exception("Não foi possível acessar a URL informada.")
        
    texto_noticia = trafilatura.extract(downloaded)
    if not texto_noticia:
        raise Exception("Não foi possível extrair o texto principal da notícia.")

    # 3. Análise da OpenAI focada estritamente em Figuras Públicas
    print("🤖 Identificando Figuras Públicas e Autoridades no texto...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um editor de imagem de telejornalismo.
    1. Identifique TODOS OS NOMES DE FIGURAS PÚBLICAS, POLÍTICOS, AUTORIDADES E LOCAIS REAIS mencionados na notícia.
    2. Crie um roteiro de 1.100 a 1.300 palavras em 8 blocos narrativos.
    3. Para cada bloco, forneça uma lista com os NOMES DAS PESSOAS OU LOCAIS REAIS citados no trecho.

    REGRA DE OURO: NUNCA sugira objetos, desenhos, animais ou termos abstratos. Apontar SOMENTE nomes de pessoas reais ou cargos públicos.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "figuras_publicas_mencionadas": ["Nome 1", "Nome 2", "Nome 3"],
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado...",
          "pessoas_citadas": ["Nome da Pessoa 1", "Nome da Pessoa 2"]
        }}
      ]
    }}

    Notícia:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um gerador de roteiros focado estritamente em nomes de figuras públicas reais."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    figuras_gerais = dados.get("figuras_publicas_mencionadas", ["Noticia Brasil"])
    roteiro = dados["roteiro"]
    print(f"👤 Figuras Públicas Identificadas: {figuras_gerais}")

    # 4. Renderização das Imagens (Troca a cada 7s + Edição de Zoom em 100% das fotos)
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    pool_fotos_reais = []  # Backup contendo apenas fotos reais de figuras públicas do artigo
    global_scene_counter = 0

    # Baixa e valida a foto de capa original como primeiro item do pool
    if foto_capa_original:
        try:
            res_capa = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if res_capa.status_code == 200:
                pool_fotos_reais.append(res_capa.content)
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

        # B. Duração e cálculo de troca exata a cada ~7 segundos
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Duração: {duration:.1f}s | Montando {num_segments} fotos (~{sub_duration:.1f}s por foto)")

        pessoas_bloco = bloco.get("pessoas_citadas", figuras_gerais)
        sub_videos_list = []

        for j in range(num_segments):
            nome_pessoa = pessoas_bloco[j % len(pessoas_bloco)]
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            imagem_salva = False

            # Primeira cena do vídeo usa a foto de capa oficial da notícia
            if idx == 0 and j == 0 and pool_fotos_reais:
                imagem_salva = salvar_imagem_sem_distorcao(pool_fotos_reais[0], img_path)

            # 1. Busca foto real no Wikimedia Commons
            if not imagem_salva:
                print(f"   📸 Buscando figura pública (Wikimedia): '{nome_pessoa}'")
                img_url = buscar_wikimedia_commons(nome_pessoa)
                if img_url:
                    try:
                        res = requests.get(img_url, timeout=8)
                        imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                        if imagem_salva and res.content not in pool_fotos_reais:
                            pool_fotos_reais.append(res.content)
                    except Exception:
                        imagem_salva = False

            # 2. Busca foto real no DuckDuckGo
            if not imagem_salva:
                print(f"   🔎 Buscando figura pública (DuckDuckGo): '{nome_pessoa}'")
                img_url = buscar_imagem_ddg(nome_pessoa)
                if img_url:
                    try:
                        res = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                        imagem_salva = salvar_imagem_sem_distorcao(res.content, img_path)
                        if imagem_salva and res.content not in pool_fotos_reais:
                            pool_fotos_reais.append(res.content)
                    except Exception:
                        imagem_salva = False

            # 3. Fallback estritamente de Pessoas Reais (NUNCA usa imagem genérica)
            if not imagem_salva:
                print(f"   ⚠️ Usando foto de outra figura pública da notícia como backup.")
                if pool_fotos_reais:
                    foto_backup = pool_fotos_reais[global_scene_counter % len(pool_fotos_reais)]
                    salvar_imagem_sem_distorcao(foto_backup, img_path)
                else:
                    # Tenta última busca genérica pelas figuras principais da matéria
                    figura_backup = figuras_gerais[0]
                    img_url = buscar_wikimedia_commons(figura_backup) or buscar_imagem_ddg(figura_backup)
                    if img_url:
                        res = requests.get(img_url, timeout=8)
                        salvar_imagem_sem_distorcao(res.content, img_path)

            # C. EDIÇÃO OBRIGATÓRIA EM TODAS AS FOTOS: Efeito Zoom In e Zoom Out
            global_scene_counter += 1
            frames = int(sub_duration * 25)
            
            if global_scene_counter % 2 == 0:
                # Efeito Zoom In
                zoom_filter = f"scale=2560:1440,zoompan=z='min(zoom+0.0015,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080,fps=25"
            else:
                # Efeito Zoom Out
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

        # D. Unir sub-cenas do bloco e sincronizar com o áudio
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
    
