import sys
import time
import json
import os
import requests
import urllib3
import gc # 🧹 Il nostro Netturbino della RAM
from pypdf import PdfReader 
import threading 
from urllib.parse import urljoin, urlparse
from google import genai

from flask import Flask, jsonify
from flask_cors import CORS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# IMPORTIAMO SELENIUM E I SUOI STRUMENTI
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service 
from webdriver_manager.chrome import ChromeDriverManager 
from selenium.webdriver.common.by import By

# =================================================================
# 1. CONFIGURAZIONE ASSOLUTA
# =================================================================
CHIAVE_GOOGLE = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=CHIAVE_GOOGLE)

URL_GESTIONALE = "https://www.studioodos.it/api_bandi_sync.php?token=ODOS_PYTHON_GEMINI_SYNC_2026"

# 🔥 PAROLE CHIAVE POTENZIATE 
PAROLE_CHIAVE = [
    'bando', 'bandi', 'avviso', 'agevolazione', 'finanziamento', 'contributo', 
    'voucher', 'pnrr', 'fesr', 'fondo perduto', 'incentivo', 'sovvenzione', 
    'digitalizzazione', 'intelligenza artificiale', 'ia', 'ai', 'triage', 
    'sanità', 'sanita', 'salute', 'telemedicina', 'innovazione', 'startup', 
    'donne', 'imprenditoria', 'sportello'
]

app = Flask(__name__)
CORS(app)

RADAR_IN_ESECUZIONE = False

# =================================================================
# 2. MOTORE DEL BROWSER E LETTURA (Blindato contro OOM Crash)
# =================================================================
def configura_browser():
    chrome_options = Options()
    
    # 🔥 LA MAGIA: Ferma il caricamento della pagina appena c'è il testo, ignorando la grafica pesante!
    chrome_options.page_load_strategy = 'eager' 
    
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu") 
    chrome_options.add_argument("--incognito") 
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    # Disabilitiamo anche Javascript per risparmiare ancora più RAM (I siti della regione non ne hanno bisogno per i link)
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.geolocation": 2,
        "profile.managed_default_content_settings.javascript": 2 # <-- Nuovo blocco anti-pesantezza
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
    })
    
    # Abbassiamo il timeout a 20 secondi: se una pagina è bloccata, la saltiamo!
    driver.set_page_load_timeout(20) 
    return driver
def estrai_testo_da_pdf_online(url_pdf):
    print(f"   📄 Estrazione PDF da: {url_pdf[:70]}...")
    nome_file_temp = "temp_bando.pdf"
    
    headers_ninja = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        # Timeout rigido: se in 15 secondi non scarica il PDF regionale, scappiamo per salvare il server
        risposta = requests.get(url_pdf, headers=headers_ninja, stream=True, timeout=15, verify=False)
        if risposta.status_code != 200: return ""
        
        with open(nome_file_temp, 'wb') as f:
            f.write(risposta.content)
            
        testo = ""
        with open(nome_file_temp, 'rb') as f:
            lettore = PdfReader(f)
            # 💡 SALVAVITA RAM: Legge solo le prime 5 pagine per evitare crash (i dati chiave sono lì)
            pagine = min(len(lettore.pages), 5) 
            for i in range(pagine):
                testo += lettore.pages[i].extract_text() + "\n"
        
        os.remove(nome_file_temp)
        return testo
    except Exception as e:
        if os.path.exists(nome_file_temp): os.remove(nome_file_temp)
        return ""

def analizza_e_salva(testo_bando, link_fonte):
    if not testo_bando or len(testo_bando.strip()) < 100: return

    print("   🧠 Gemini sta analizzando (anti-ban 8s)...")
    time.sleep(8)
    
    prompt = f"""
    Analizza questo bando pubblico o documento agevolativo.
    Sei un europrogettista. Devi dirmi se questo bando finanzia (o è compatibile con) ALMENO UNO di questi settori:
    1. Studi medici, ambulatori, professioni sanitarie (ATECO 86.90.29 / 86.22)
    2. Digitalizzazione d'impresa, Intelligenza Artificiale, automazione segreteria
    3. Innovazione dei processi (es. Sistemi di Triage automatizzati).
    
    Se è compatibile con ALMENO UNO dei punti sopra, imposta "compatibile_ateco_869029" a true.
    Se finanzia a FONDO PERDUTO (anche in parte), imposta "fondo_perduto" a true.
    
    Rispondi SOLO con un JSON valido (senza markdown):
    {{"compatibile_ateco_869029": bool, "fondo_perduto": bool, "percentuale_copertura": "es. 70%", "spese_ammissibili": "Riassunto max 20 parole", "scadenza": "YYYY-MM-DD oppure Non specificata", "titolo_bando": "Titolo ufficiale"}}
    
    Testo da analizzare: {testo_bando[:15000]} 
    """
    
    massimo_tentativi = 3
    for tentativo in range(massimo_tentativi):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            json_text = response.text.strip().replace('```json', '').replace('```', '')
            dati_ai = json.loads(json_text)
            
            titolo = dati_ai.get('titolo_bando', 'Bando Senza Titolo')
            
            if dati_ai.get('compatibile_ateco_869029') and dati_ai.get('fondo_perduto'):
                dati_ai['link_bando'] = link_fonte 
                dati_ai['ente_erogatore'] = "Radar Odós"
                dati_ai['titolo'] = titolo
                
                # --- 🛡️ PASSAPORTO DIPLOMATICO PER IL SERVER PHP (Anti-Firewall) ---
                headers_ninja_post = {
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Origin": "https://www.studioodos.it",
                    "Referer": "https://www.studioodos.it/bandi.php",
                    "Connection": "keep-alive"
                }
                
                risposta_server = requests.post(URL_GESTIONALE, json=dati_ai, headers=headers_ninja_post, verify=False, timeout=10)
                
                print(f"   ✅ [BINGO!] TROVATO E TRASMESSO: {titolo}")
                print(f"   📡 Risposta Server Odós: {risposta_server.text}")
            else:
                print(f"   ❌ Scartato (No requisiti IA/Sanità/Fondo Perduto): {titolo[:50]}...")
            break 
            
        except Exception as e:
            if "503" in str(e): 
                print("   ⏳ Gemini occupato (503), riprovo...")
                time.sleep(5)
                continue
            print(f"   ⚠️ Errore Gemini/JSON: {str(e)[:100]}")
            break

    # 🧹 PULIZIA RAM POST-ANALISI
    del testo_bando
    gc.collect()

# =================================================================
# 3. LO SMART SPIDER
# =================================================================
def scansiona_sito_totale(driver, url_partenza):
    dominio_base = urlparse(url_partenza).netloc
    link_visitati = set()
    link_da_visitare = [url_partenza]
    pdf_trovati_e_analizzati = set()
    
    LIMITE_PAGINE_WEB = 5 
    LIMITE_PDF_PER_SITO = 2 
    pagine_scansionate = 0
    
    while link_da_visitare and pagine_scansionate < LIMITE_PAGINE_WEB:
        url_corrente = link_da_visitare.pop(0) 
        if url_corrente in link_visitati: continue
            
        print(f"🕸️ Navigo in: {url_corrente}")
        link_visitati.add(url_corrente)
        pagine_scansionate += 1
        
        try:
            driver.get(url_corrente)
            time.sleep(3) 
            
            # Analisi anche del testo HTML (decreti online)
            testo_pagina = driver.find_element(By.TAG_NAME, "body").text
            if any(p in testo_pagina.lower() for p in ['fondo perduto', 'agevolazione', 'finanziamento']):
                analizza_e_salva(testo_pagina, url_corrente)

            tutti_i_tag_a = driver.find_elements(By.TAG_NAME, "a")
            
            for tag in tutti_i_tag_a:
                href = tag.get_attribute('href')
                if not href: continue
                testo_link = tag.text.lower()
                href = urljoin(url_corrente, href)
                
                if href.lower().endswith('.pdf'):
                    if href not in pdf_trovati_e_analizzati and len(pdf_trovati_e_analizzati) < LIMITE_PDF_PER_SITO:
                        pdf_trovati_e_analizzati.add(href)
                        testo_pdf = estrai_testo_da_pdf_online(href)
                        analizza_e_salva(testo_pdf, href) 
                
                elif dominio_base in urlparse(href).netloc and href not in link_visitati and href not in link_da_visitare:
                    if any(parola in href.lower() or parola in testo_link for parola in PAROLE_CHIAVE):
                        link_da_visitare.append(href)
                        
        except Exception as e:
            errore = str(e).lower()
            if "localhost" in errore or "timed out" in errore or "memory" in errore:
                print("   🚨 Chrome in Sofferenza RAM. Fuga tattica dal sito!")
                break

# =================================================================
# 4. IL "LAVORATORE IN BACKGROUND"
# =================================================================
def avvia_esplorazione_in_background():
    global RADAR_IN_ESECUZIONE
    RADAR_IN_ESECUZIONE = True
    
    print("\n🚀 [THREAD BACKGROUND] Odós Smart Spider Partito!")
    
    SITI_BERSAGLIO = [
        "https://calabriaeuropa.regione.calabria.it/bando/",
        "https://www.fincalabra.it/web/bandi-e-avvisi",
        "https://www.invitalia.it/cosa-facciamo/creiamo-nuove-aziende",
        "https://www.mimit.gov.it/it/incentivi",
        "https://www.agenas.gov.it/pnrr",
        "https://www.puntoimpresadigitale.camcom.it/bandi/",
        "https://bandifincalabra.it",
        "https://www.rc.camcom.gov.it/bandi-e-concorsi/bandi-di-gara"
    ]

    try:
        for sito in SITI_BERSAGLIO:
            print(f"\n{'='*60}\n🌐 INIZIO SCANSIONE PROFONDA: {sito}\n{'='*60}")
            driver = None
            try:
                driver = configura_browser() 
                scansiona_sito_totale(driver, sito)
            except Exception as error_sito:
                print(f"⚠️ Errore o timeout sul sito {sito}: {error_sito}")
            finally:
                if driver: 
                    driver.quit() 
                    print("🧹 Browser chiuso, RAM azzerata per questo sito.")
                # 🧹 PULIZIA RAM TOTALE FRA UN SITO E L'ALTRO
                gc.collect()
                    
    except Exception as e:
        print(f"🆘 Errore Critico Globale: {str(e)}")
    finally:
        RADAR_IN_ESECUZIONE = False
        print("🏁 Scansione Totale Terminata. Pronto per il prossimo comando.")

# =================================================================
# 5. LE ROTTE FLASK
# =================================================================
@app.route('/')
def home():
    return "Server Odós Attivo! Prova a lanciare il radar dalla tua Dashboard."

@app.route('/avvia-radar', methods=['POST', 'GET'])
def api_avvia_radar():
    global RADAR_IN_ESECUZIONE
    
    if RADAR_IN_ESECUZIONE:
        return jsonify({"status": "error", "message": "Il Radar sta già scansionando il web! Attendi."}), 429
    
    thread = threading.Thread(target=avvia_esplorazione_in_background)
    thread.start()
    
    return jsonify({"status": "success", "message": "Radar avviato correttamente in background!"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🟢 SERVER RADAR ODÓS ACCESO SULLA PORTA {port}...")
    app.run(host='0.0.0.0', port=port)
