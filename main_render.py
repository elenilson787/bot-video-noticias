import os
import json
import math
import random
import hashlib
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

def calcular_hash_imagem(binary_content):
    """Gera um MD5 único dos bytes da imagem para evitar duplicadas"""
    return hashlib.md5(binary_content).hexdigest()

def salvar_imagem_sem_distorcao(binary_content, target_path):
    """Ajusta a foto no enquadramento 16:9 (1920x1080) SEM esticar"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Imagem inválida descartada: {e}")
        return False

def buscar_wikimedia_commons(termo):
    """Busca fotos e mapas contextuais no Wikimedia Commons (API Livre)"""
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

def buscar_imagem_ddg(termo):
    """Busca imagens e mapas contextuais no DuckDuckGo"""
    try:
        results = DDGS().images(keywords=f"{termo}", max_results=4)
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

    # 3. Análise da OpenAI com Termos Visuais Contextuais e Seguros
    print("🤖 Analisando contexto da notícia e gerando termos de busca visuais e seguros...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um editor de arte e diretor de documentários jornalísticos.
    Sua missão é analisar o texto da notícia e criar termos de busca VISUAIS EXATOS, CONTEXTUAIS E SEGUROS para acompanhar a narração.

    REGRAS DE OURO PARA BUSCA DE IMAGEM:
    1. CONTEXTO GEOGRÁFICO/LOCAL: Se o texto narrar ataques ou conflitos em uma região (ex: Faixa de Gaza, Ucrânia, Washington), NÃO busque por violência explícita. Busque por termos de contexto geográfico ou representação territorial, como:
       - "Gaza Strip map"
       - "Gaza aerial view"
       - "Middle East geography map"
       - "Washington DC aerial view"
    2. FIGURAS PÚBLICAS E POLÍTICA: Se citar pessoas ou governos, busque pelos nomes reais ou locais oficiais:
       - "Donald Trump speech"
       - "White House press room"
       - "Palácio do Planalto Brasília"
       - "United Nations Assembly hall"
    3. Cenas a cada 7 segundos: Para cada bloco narrativo, forneça de 5 a 7 termos de busca ULTRA CONTEXTUAIS em inglês ou português que correspondam EXATAMENTE ao assunto narrado naquele trecho específico.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "figuras_gerais": ["Nome 1", "Local 1"],
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado para este trecho...",
          "termos_busca_cenas": [
            "termo contextual 1",
            "termo contextual 2",
            "termo contextual 3",
            "termo contextual 4",
            "termo contextual 5"
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
            {"role": "system", "content": "Você é um gerador de roteiros focado em representação visual contextual e segura para o YouTube."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    figuras_gerais = dados.get("figuras_gerais") or ["Noticia Brasil"]
    roteiro = dados["roteiro"]

    # 4. Controle de Imagens Únicas e Anti-Repetição
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    pool_imagens_unicas = {}
    historico_exibicao = [] 

    # Adiciona a capa oficial do artigo como opção inicial
    if foto_capa_original:
        try:
            res_capa = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if res_capa.status_code == 200:
                h = calcular_hash_imagem(res_capa.content)
                pool_imagens_unicas[h] = res_capa.content
        except Exception:
            pass

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

        # B. Duração e cálculo exato de imagens (~7 segundos por imagem)
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Narração: {duration:.1f}s | Criando {num_segments} cenas contextuais (~{sub_duration:.1f}s cada)")

        termos_cenas = bloco.get("termos_busca_cenas") or figuras_gerais
        sub_videos_list = []

        for j in range(num_segments):
            termo = termos_cenas[j % len(termos_cenas)]
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            imagem_salva = False
            bytes_imagem_escolhida = None

            # 1. Primeira cena do vídeo usa a foto oficial da capa da matéria
            if idx == 0 and j == 0 and pool_imagens_unicas:
                bytes_imagem_escolhida = list(pool_imagens_unicas.values())[0]
                imagem_salva = salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)

            # 2. Busca termo contextual no Wikimedia Commons (Mapas, Territórios, Fotos Oficiais)
            if not imagem_salva:
                print(f"   📸 Cena {scene_counter + 1} | Buscando imagem contextual (Wikimedia): '{termo}'")
                img_url = buscar_wikimedia_commons(termo)
                if img_url:
                    try:
                        res = requests.get(img_url, timeout=8)
                        h = calcular_hash_imagem(res.content)
                        if h not in pool_imagens_unicas:
                            pool_imagens_unicas[h] = res.content
                            bytes_imagem_escolhida = res.content
                            imagem_salva = salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)
                    except Exception:
                        imagem_salva = False

            # 3. Busca termo contextual no DuckDuckGo
            if not imagem_salva:
                print(f"   🔎 Cena {scene_counter + 1} | Buscando imagem contextual (DuckDuckGo): '{termo}'")
                img_url = buscar_imagem_ddg(termo)
                if img_url:
                    try:
                        res = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                        h = calcular_hash_imagem(res.content)
                        if h not in pool_imagens_unicas:
                            pool_imagens_unicas[h] = res.content
                            bytes_imagem_escolhida = res.content
                            imagem_salva = salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)
                    except Exception:
                        imagem_salva = False

            # 4. FALLBACK INTELIGENTE ANTI-REPETIÇÃO CONSECUTIVA
            if not imagem_salva:
                print(f"   ⚠️ Reutilizando imagem do banco com filtro de variedade.")
                todas_chaves_hashes = list(pool_imagens_unicas.keys())
                
                if len(todas_chaves_hashes) > 0:
                    hashes_proibidos = historico_exibicao[-2:] if len(historico_exibicao) >= 2 else historico_exibicao[-1:]
                    hashes_permitidos = [h for h in todas_chaves_hashes if h not in hashes_proibidos]
                    
                    if not hashes_permitidos:
                        hashes_permitidos = todas_chaves_hashes

                    hash_escolhido = hashes_permitidos[scene_counter % len(hashes_permitidos)]
                    bytes_imagem_escolhida = pool_imagens_unicas[hash_escolhido]
                    salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)
                    h_atual = hash_escolhido
                else:
                    res = requests.get("https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1200", timeout=8)
                    salvar_imagem_sem_distorcao(res.content, img_path)
                    h_atual = "fallback"
            else:
                h_atual = calcular_hash_imagem(bytes_imagem_escolhida)

            historico_exibicao.append(h_atual)
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

        # D. Sincronizar sub-cenas do bloco com a narração
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
            
