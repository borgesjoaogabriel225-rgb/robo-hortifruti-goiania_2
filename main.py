import os
import re
import time
import threading
from datetime import datetime
from flask import Flask
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
import google.generativeai as genai

# ==========================================
# 0. SERVIDOR WEB PARA ENGANAR O RENDER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Robô Hortifruti Goiânia rodando perfeitamente!", 200

# ==========================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("As variáveis SUPABASE_URL e SUPABASE_SERVICE_KEY precisam estar configuradas.")

# Inicializa o cliente do Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Configura a IA Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

FRUTAS_ALVO = [
    "Maçã Fuji", "Banana Prata", "Laranja Pêra", "Mamão Formosa", "Melancia",
    "Abacaxi Pérola", "Melão Amarelo", "Pêra Willians", "Manga Palmer", "Uva Thompson",
    "Limão Tahiti", "Mexerica", "Goiaba Vermelha", "Maracujá Azedo", "Morango"
]

SUPERMERCADOS = ["atacadao", "assai", "tatico", "bretas", "carrefour"]

# ==========================================
# PILAR 1: COLETOR LEVE DE DADOS (HTTP + BS4)
# ==========================================
def raspar_precos_supermercado(supermercado: str) -> str:
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

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"⚠️ Erro ao aceder a {supermercado}: {e}")

    return ""

# ==========================================
# PILAR 2: TRATAMENTO COM IA (GEMINI)
# ==========================================
def tratar_dados_com_ia(texto_bruto: str, supermercado: str) -> dict:
    if not texto_bruto or not GEMINI_API_KEY:
        return {}

    prompt = f"""
    Você é um assistente especialista em extração de preços de e-commerce.
    Analise o texto bruto extraído do site do supermercado '{supermercado}' em Goiânia.

    Identifique os preços por Kg ou Unidade das seguintes frutas:
    {FRUTAS_ALVO}

    Regras:
    1. Retorne ESTRITAMENTE um JSON válido com a fruta e o preço em número float (ex: 5.99).
    2. Se a fruta não for encontrada, defina o valor como null.

    Texto:
    ---
    {texto_bruto[:6000]}
    ---
    """

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        json_str = re.sub(r"```json\n|\n```", "", response.text).strip()
        import json
        return json.loads(json_str)
    except Exception as e:
        print(f"⚠️ Erro no processamento da IA ({supermercado}): {e}")
        return {}

# ==========================================
# ATUALIZAÇÃO EM TEMPO REAL NO SUPABASE
# ==========================================
def atualizar_supabase(dados_por_supermercado: dict):
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    try:
        resposta = supabase.table("precos_hortifruti").select("*").execute()
        registros_atuais = {row["fruta"]: row for row in resposta.data}
    except Exception as e:
        print(f"⚠️ Erro ao consultar o Supabase: {e}")
        return

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

        if alteracao_detectada:
            novos_precos["data_atualizacao"] = hoje
            supabase.table("precos_hortifruti").update(novos_precos).eq("fruta", fruta).execute()
            print(f"⚡ [TEMPO REAL] Preço de '{fruta}' atualizado no Supabase!")

# ==========================================
# LOOP CONTINUO DE EXECUÇÃO
# ==========================================
def executar_agente():
    print("🚀 Agente Autônomo Hortifruti Iniciado...")
    while True:
        print(f"\n[Ciclo iniciado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}]")
        resultados = {}

        for mercado in SUPERMERCADOS:
            print(f"🔍 Verificando {mercado.upper()}...")
            texto = raspar_precos_supermercado(mercado)
            if texto:
                precos = tratar_dados_com_ia(texto, mercado)
                resultados[mercado] = precos

        atualizar_supabase(resultados)
        print("⏳ Aguardando 15 minutos para a próxima verificação...")
        time.sleep(900)

# ==========================================
# INICIALIZAÇÃO DUAL (FLASK + ROBÔ)
# ==========================================
if __name__ == "__main__":
    # Inicia a thread do robô em segundo plano
    t = threading.Thread(target=executar_agente)
    t.daemon = True
    t.start()

    # Inicia o servidor Flask na porta atribuída pelo Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
