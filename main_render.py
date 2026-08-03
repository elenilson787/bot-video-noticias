import os
import json
import math
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
    """Gera um MD5 único dos bytes para evitar fotos idênticas"""
    return hashlib.md5(binary_content).hexdigest()

def salvar_imagem_sem_distorcao(binary_content, target_path):
    """Ajusta a foto no enquadramento 16:9 (1920x1080) SEM esticar o rosto"""
    try:
        img = Image.open(BytesIO(binary_content)).convert('RGB')
        img_fitted = ImageOps.fit(img, (1920, 1080), Image.Resampling.LANCZOS)
        img_fitted.save(target_path, 'JPEG', quality=95)
        return True
    except Exception as e:
        print(f"⚠️ Imagem descartada: {e}")
        return False

def buscar_imagem_wikipedia(termo):
    """Busca fotos oficiais diretamente na API da Wikipedia (100% Livre de Bloqueios)"""
    headers = {'User-Agent': 'BotNoticias/3.0 (https://github.com)'}
    for lang in ["pt", "en"]:
        try:
            url_search = f"https://{lang}.wikipedia.org/w/api.php"
            params_search = {
                "action": "query",
                "list": "search",
                "srsearch": termo,
                "utf8": "1",
                "format": "json"
            }
            res_search = requests.get(url_search, params=params_search, headers=headers, timeout=6)
            search_results = res_search.json().get("query", {}).get("search", [])
            
            if search_results:
                page_title = search_results[0]["title"]
                params_img = {
                    "action": "query",
                    "titles": page_title,
                    "prop": "pageimages",
                    "pithumbsize": "1200",
                    "format": "json"
                }
                res_img = requests.get(url_search, params=params_img, headers=headers, timeout=6)
                pages = res_img.json().get("query", {}).get("pages", {})
                for p_id, p_info in pages.items():
                    thumbnail = p_info.get("thumbnail", {}).get("source")
                    if thumbnail:
                        return thumbnail
        except Exception:
            pass
    return None

def buscar_imagem_ddg(termo):
    """Busca fotos jornalísticas e geográficas no DuckDuckGo"""
    try:
        results = DDGS().images(keywords=f"{termo} noticia", max_results=3)
        if results:
            for item in results:
                img_url = item.get("image")
                if img_url and img_url.startswith("http"):
                    return img_url
    except Exception:
        pass
    return None

def extrair_foto_capa_noticia(url):
    """Extrai a foto de capa original da matéria"""
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

    # 3. Análise da OpenAI
    print("🤖 Gerando termos de busca contextuais baseados no texto...")
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""
    Você é um diretor de arte de telejornalismo.
    1. Crie um roteiro de 1.100 a 1.300 palavras em 8 blocos narrativos.
    2. Identifique uma lista geral com os 5 a 8 NOMES DE PESSOAS, LOCAIS, MAPAS OU GOVERNOS mais importantes da matéria.
    3. Para CADA BLOCO, forneça de 5 a 6 termos de busca específicos e variados (em inglês ou português) para acompanhar a narração sem apelar para violência explícita.

    Retorne ESTRITAMENTE um JSON no formato:
    {{
      "figuras_gerais": ["Nome/Local 1", "Nome/Local 2", "Nome/Local 3", "Nome/Local 4"],
      "roteiro": [
        {{
          "bloco": 1,
          "narracao": "Texto narrado para este trecho...",
          "termos_busca_cenas": ["Termo 1", "Termo 2", "Termo 3", "Termo 4"]
        }}
      ]
    }}

    Notícia:
    {texto_noticia}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um gerador de roteiros focado em representação visual dinâmica e contextual."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    dados = json.loads(response.choices[0].message.content)
    figuras_gerais = dados.get("figuras_gerais") or ["Notícia"]
    roteiro = dados["roteiro"]

    # 4. Inicialização Dinâmica do Banco de Imagens (Apenas Conteúdo Real da Notícia)
    os.makedirs("output", exist_ok=True)
    concat_block_list = []
    pool_imagens_unicas = {}
    historico_exibicao = [] 

    print("⚡ Construindo banco de imagens dinâmico a partir dos temas da notícia...")
    
    # Adiciona a foto oficial de capa do artigo
    if foto_capa_original:
        try:
            res_capa = requests.get(foto_capa_original, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if res_capa.status_code == 200:
                h = calcular_hash_imagem(res_capa.content)
                pool_imagens_unicas[h] = res_capa.content
        except Exception:
            pass

    # Pré-busca fotos reais para os temas principais identificados pela IA
    for entidade in figuras_gerais:
        url_img = buscar_imagem_wikipedia(entidade) or buscar_imagem_ddg(entidade)
        if url_img:
            try:
                res_ent = requests.get(url_img, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
                if res_ent.status_code == 200:
                    h = calcular_hash_imagem(res_ent.content)
                    if h not in pool_imagens_unicas:
                        pool_imagens_unicas[h] = res_ent.content
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

        # B. Duração e cálculo de imagens (~7 segundos por imagem)
        duration = get_media_duration(audio_path)
        num_segments = max(1, math.ceil(duration / 7.0))
        sub_duration = duration / num_segments
        print(f"⏱️ Duração: {duration:.1f}s | Criando {num_segments} cenas (~{sub_duration:.1f}s cada)")

        termos_cenas = bloco.get("termos_busca_cenas") or figuras_gerais
        sub_videos_list = []

        for j in range(num_segments):
            termo = termos_cenas[j % len(termos_cenas)]
            sub_video_path = os.path.abspath(f"output/sub_{idx}_{j}.mp4")
            img_path = os.path.abspath(f"output/img_{idx}_{j}.jpg")

            imagem_salva = False
            bytes_imagem_escolhida = None

            # 1. Busca imagem real no Wikipedia ou DuckDuckGo para o termo da cena
            print(f"   📸 Cena {scene_counter + 1} | Buscando: '{termo}'")
            img_url = buscar_imagem_wikipedia(termo) or buscar_imagem_ddg(termo)
            
            if img_url:
                try:
                    res = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                    if res.status_code == 200:
                        h = calcular_hash_imagem(res.content)
                        if h not in pool_imagens_unicas:
                            pool_imagens_unicas[h] = res.content
                        bytes_imagem_escolhida = res.content
                        imagem_salva = salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)
                except Exception as e:
                    print(f"   ⚠️ Download falhou para '{termo}': {e}")
                    imagem_salva = False

            # 2. FALLBACK ANTI-REPETIÇÃO CONSECUTIVA (Usando apenas o pool dinâmico da notícia)
            if not imagem_salva:
                print(f"   ⚠️ Selecionando foto do pool da notícia com filtro anti-duplicidade.")
                todas_chaves_hashes = list(pool_imagens_unicas.keys())
                
                if todas_chaves_hashes:
                    # Impede repetição com a cena anterior e a penúltima
                    hashes_proibidos = historico_exibicao[-2:] if len(historico_exibicao) >= 2 else historico_exibicao[-1:]
                    hashes_permitidos = [h for h in todas_chaves_hashes if h not in hashes_proibidos]
                    
                    if not hashes_permitidos:
                        hashes_permitidos = todas_chaves_hashes

                    hash_escolhido = hashes_permitidos[scene_counter % len(hashes_permitidos)]
                    bytes_imagem_escolhida = pool_imagens_unicas[hash_escolhido]
                    salvar_imagem_sem_distorcao(bytes_imagem_escolhida, img_path)
                    h_atual = hash_escolhido
                else:
                    # Caso extremo: re-tenta busca geral pelo tema principal
                    res = requests.get(buscar_imagem_ddg(figuras_gerais[0]), timeout=8)
                    salvar_imagem_sem_distorcao(res.content, img_path)
                    h_atual = calcular_hash_imagem(res.content)
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
    
