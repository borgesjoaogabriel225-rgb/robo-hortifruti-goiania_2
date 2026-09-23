import os
import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from supabase import create_client, Client
import google.generativeai as genai

# ==========================================
# 1. CONFIGURAÇÃO DE CREDENCIAIS E APIS
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://uytvwuxmemkrdculoawo.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

# Inicializa o cliente do Supabase com privilégios de escrita
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Configura a chave de API da LLM (Gemini / OpenAI)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI")
genai.configure(api_key=GEMINI_API_KEY)

# Lista oficial das 15 frutas monitoradas
FRUTAS_ALVO = [
    "Maçã Fuji", "Banana Prata", "Laranja Pêra", "Mamão Formosa", "Melancia",
    "Abacaxi Pérola", "Melão Amarelo", "Pêra Willians", "Manga Palmer", "Uva Thompson",
    "Limão Tahiti", "Mexerica", "Goiaba Vermelha", "Maracujá Azedo", "Morango"
]

SUPERMERCADOS = ["atacadao", "assai", "tatico", "bretas", "carrefour"]

# ==========================================
# PILAR 1: SCRAPER / RASPAGEM DE DADOS
# ==========================================
def raspar_precos_supermercado(supermercado: str):
    """
    Acessa o site/e-commerce do supermercado via Playwright e captura
    o texto bruto com os nomes dos produtos e preços listados.
    """
    dados_brutos = []
    
    # URLs de busca/categoria de hortifrúti dos e-commerces em Goiânia
    urls = {
        "atacadao": "https://www.atacadao.com.br/hortifruti/frutas",
        "assai": "https://www.assai.com.br/e-commerce/goiania/frutas",
        "tatico": "https://www.tatico.com.br/goiania/hortifruti",
        "bretas": "https://www.bretas.com.br/hortifruti",
        "carrefour": "https://www.carrefour.com.br/colecao-hortifruti"
    }

    url = urls.get(supermercado)
    if not url:
        return ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            # Extrai todo o conteúdo de texto da página contendo produtos e preços
            texto_pagina = page.inner_text("body")
            dados_brutos.append(texto_pagina)
        except Exception as e:
            print(f"Erro ao acessar {supermercado}: {e}")
        finally:
            browser.close()

    return "\n".join(dados_brutos)

# ==========================================
# PILAR 2: TRATAMENTO E NORMALIZAÇÃO COM IA (LLM)
# ==========================================
def tratar_dados_com_ia(texto_bruto: str, supermercado: str) -> dict:
    """
    O cérebro de IA recebe o texto desestruturado da página, identifica
    as 15 frutas da nossa cesta, padroniza variações (ex: 'Ban. Prata Kg' -> 'Banana Prata')
    e extrai o preço numérico do Kg.
    """
    prompt = f"""
    Você é um agente especialista em parsing de dados de supermercados em Goiânia.
    Abaixo está o texto bruto extraído do e-commerce do supermercado '{supermercado}'.

    Análise o texto e encontre o preço por Kg ou Unidade das seguintes frutas exatas:
    {FRUTAS_ALVO}

    Regras:
    1. Padronize variações de nome para o nome exato da lista acima (ex: 'Banana Prata Selecionada' -> 'Banana Prata').
    2. Retorne APENAS um objeto JSON válido, onde a chave é o nome exato da fruta e o valor é o preço em float (ex: 5.99).
    3. Se a fruta não for encontrada no texto, atribua null.

    Texto bruto para análise:
    ---
    {texto_bruto[:8000]}
    ---
    """

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
    import json
    try:
        # Limpa formatação Markdown do retorno da LLM para extrair o JSON puro
        json_str = re.sub(r'```json\n|\n```', '', response.text).strip()
        precos_extraidos = json.loads(json_str)
        return precos_extraidos
    except Exception as e:
        print(f"Erro no processamento da IA para {supermercado}: {e}")
        return {}

# ==========================================
# MÓDULO DE ATUALIZAÇÃO EM TEMPO REAL NO SUPABASE
# ==========================================
def atualizar_supabase(dados_por_supermercado: dict):
    """
    Compara os preços capturados pela IA com os dados atuais no Supabase.
    Se houver qualquer alteração de preço, atualiza a tabela imediatamente.
    """
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    # Busca os registros atuais no Supabase
    resposta = supabase.table("precos_hortifruti").select("*").execute()
    registros_atuais = {row["fruta"]: row for row in resposta.data}

    for fruta in FRUTAS_ALVO:
        novos_precos = {}
        alteracao_detectada = False
        
        row_atual = registros_atuais.get(fruta, {})

        for mercado in SUPERMERCADOS:
            preco_novo = dados_por_supermercado.get(mercado, {}).get(fruta)
            preco_antigo = row_atual.get(mercado)

            if preco_novo is not None and preco_novo != preco_antigo:
                novos_precos[mercado] = float(preco_novo)
                alteracao_detectada = True
            elif preco_antigo is not None:
                novos_precos[mercado] = float(preco_antigo)

        # Atualiza a linha no Supabase apenas se um preço mudou
        if alteracao_detectada:
            novos_precos["data_atualizacao"] = hoje
            supabase.table("precos_hortifruti").update(novos_precos).eq("fruta", fruta).execute()
            print(f"⚡ [TEMPO REAL] Preço da fruta '{fruta}' atualizado no Supabase!")

# ==========================================
# LOOP CONTINUO DE MONITORAMENTO
# ==========================================
def executar_agente_autonomo():
    """
    Executa a varredura em ciclo contínuo (ex: a cada 15 minutos)
    garantindo que qualquer mudança de preço seja refletida instantaneamente no App.
    """
    print("🚀 Agente Autônomo de Coleta e IA iniciado...")
    
    while True:
        print(f"\n[Varredura Iniciada: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}]")
        resultados_totais = {}

        for mercado in SUPERMERCADOS:
            print(f"🔍 Coletando dados de: {mercado.upper()}...")
            texto_bruto = raspar_precos_supermercado(mercado)
            
            if texto_bruto:
                print(f"🧠 Processando dados com IA para {mercado}...")
                precos_frutas = tratar_dados_com_ia(texto_bruto, mercado)
                resultados_totais[mercado] = precos_frutas

        # Envia para o Supabase
        atualizar_supabase(resultados_totais)
        
        # Intervalo de 15 minutos entre varreduras contínuas
        print("⏳ Aguardando próximo ciclo de monitoramento...")
        time.sleep(900)

if __name__ == "__main__":
    executar_agente_autonomo()
