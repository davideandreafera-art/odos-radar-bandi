import sys
import time
import json
import os
import requests
import urllib3
from pypdf import PdfReader # Assicurati di usare PyPDF2 se in basso chiami PyPDF2.PdfReader
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
from selenium.webdriver.common.by import By # 👈 ECCO LA RIGA DA AGGIUNGERE!

# =================================================================
# 1. CONFIGURAZIONE ASSOLUTA
# =================================================================
CHIAVE_GOOGLE = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=CHIAVE_GOOGLE)

URL_GESTIONALE = "https://www.studioodos.it/api_bandi_sync.php?token=ODOS_PYTHON_GEMINI_SYNC_2026"

PAROLE_CHIAVE = [
    'bando', 'bandi', 
    'avviso', 'avvisi', 
    'agevolazione', 'agevolazioni', 
    'finanziamento', 'finanziamenti', 
    'contributo', 'contributi', 
    'voucher', 'pid', 
    'pnrr', 'fesr', 'por', 
    'fondo perduto', 
    'incentivo', 'incentivi', 
    'sovvenzione', 'sovvenzioni', 
    'bonus','donna', 
    'manifestazione di interesse', 
    'sportello'
]

app = Flask(__name__)
CORS(app)

RADAR_IN_ESECUZIONE = False

# =================================================================
# 2. MOTORE DEL BROWSER E LETTURA PDF (Versione Ninja Anti-Blocco)
# =================================================================
def configura_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu") 
    chrome_options.add_argument("--incognito") 
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    # --- 🛡️ INIZIO SCUDO ANTI-BOT (Le modifiche magiche) ---
    # 1. Rimuove la scritta "Chrome è controllato da un software automatizzato"
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # 2. Carta d'identità perfetta di un utente Windows reale
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    # --- 🛡️ FINE SCUDO ---

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.popups": 2,
        "profile.managed_default_content_settings.geolocation": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Trucco extra per nascondere Selenium a livello Javascript
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    driver.set_page_load_timeout(60)
    return driver

def estrai_testo_da_pdf_online(url_pdf):
    print(f"   📄 Estrazione da: {url_pdf[:70]}...")
    nome_file_temp = "temp_bando.pdf"
    
    # --- 🛡️ INTESTAZIONI ANTI-BLOCCO PER I PDF ---
    headers_ninja = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive"
    }
    
    try:
        risposta = requests.get(url_pdf, headers=headers_ninja, stream=True, timeout=15, verify=False)
        with open(nome_file_temp, 'wb') as f:
            f.write(risposta.content)
            
        testo = ""
        with open(nome_file_temp, 'rb') as f:
            lettore = PyPDF2.PdfReader(f)
            pagine = min(len(lettore.pages), 10) 
            for i in range(pagine):
                testo += lettore.pages[i].extract_text() + "\n"
        os.remove(nome_file_temp)
        return testo
    except Exception as e:
        if os.path.exists(nome_file_temp): os.remove(nome_file_temp)
        return ""

def analizza_e_salva(testo_bando, link_fonte):
    if not testo_bando.strip(): return

    print("   🧠 Gemini sta analizzando i requisiti (attesa anti-blocco di 10s)...")
    time.sleep(10)
    
    prompt = f"Analizza questo testo tecnico. Rispondi SOLO con un JSON valido. Chiavi: compatibile_ateco_869029 (bool), fondo_perduto (bool), percentuale_copertura (str), spese_ammissibili (str), scadenza (YYYY-MM-DD), titolo_bando (str). Testo: {testo_bando}"
    
    massimo_tentativi = 3
    for tentativo in range(massimo_tentativi):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            json_text = response.text.strip().replace('```json', '').replace('```', '')
            dati_ai = json.loads(json_text)
            
            titolo = dati_ai.get('titolo_bando', 'Bando Senza Titolo')
            
            if dati_ai.get('compatibile_ateco_869029') and dati_ai.get('fondo_perduto'):
                dati_ai['link_bando'] = link_fonte 
                dati_ai['ente_erogatore'] = "Rilevato dallo Smart Spider"
                dati_ai['titolo'] = titolo
                
                risposta_server = requests.post(URL_GESTIONALE, json=dati_ai, headers={"Content-Type": "application/json"})
                print(f"   ✅ [BINGO!] TROVATO FONDO PERDUTO IN TARGET: {titolo}")
            else:
                print(f"   ❌ Scartato (No requisiti): {titolo}")
            break 
            
        except Exception as e:
            errore = str(e)
            print(f"   ⚠️ Errore navigando su {url_corrente} | DETTAGLIO: {errore}")
            
            # Se il browser interno (localhost) va in coma per mancanza di RAM, usciamo subito dal sito!
            if "localhost" in errore or "timed out" in errore.lower():
                print("   🚨 Motore Chrome bloccato (RAM satura). Chiudo questo sito per autodifesa e passo al prossimo!")
                break # Rompe il ciclo e passa al sito successivo svuotando la memoria
# =================================================================
# 3. LO SMART SPIDER
# =================================================================
def scansiona_sito_totale(driver, url_partenza):
    dominio_base = urlparse(url_partenza).netloc
    link_visitati = set()
    link_da_visitare = [url_partenza]
    pdf_trovati_e_analizzati = set()
    
    LIMITE_PAGINE_WEB = 10 # 👈 Limite abbassato per risparmiare RAM
    LIMITE_PDF_PER_SITO = 5
    pagine_scansionate = 0
    
    while link_da_visitare and pagine_scansionate < LIMITE_PAGINE_WEB:
        url_corrente = link_da_visitare.pop(0) 
        if url_corrente in link_visitati: continue
            
        print(f"🕸️ Navigo in: {url_corrente}")
        link_visitati.add(url_corrente)
        pagine_scansionate += 1
        
        try:
            driver.get(url_corrente)
            time.sleep(4) 
            tutti_i_tag_a = driver.find_elements(By.TAG_NAME, "a")
            
            for tag in tutti_i_tag_a:
                href = tag.get_attribute('href')
                testo = tag.text.lower()
                if not href: continue
                href = urljoin(url_corrente, href)
                
                if href.lower().endswith('.pdf'):
                    if href not in pdf_trovati_e_analizzati and len(pdf_trovati_e_analizzati) < LIMITE_PDF_PER_SITO:
                        pdf_trovati_e_analizzati.add(href)
                        testo_pdf = estrai_testo_da_pdf_online(href)
                        analizza_e_salva(testo_pdf, url_corrente)
                
                elif dominio_base in urlparse(href).netloc and href not in link_visitati and href not in link_da_visitare:
                    if any(parola in href.lower() or parola in testo for parola in PAROLE_CHIAVE):
                        link_da_visitare.append(href)
        except Exception as e:
            errore = str(e)
            print(f"   ⚠️ Errore navigando su {url_corrente} | DETTAGLIO: {errore}")
            
            # 🛡️ AUTODIFESA RAM: Se Chrome muore, esce dal sito
            if "localhost" in errore or "timed out" in errore.lower():
                print("   🚨 Motore Chrome bloccato (RAM satura). Chiudo questo sito per autodifesa e passo al prossimo!")
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
        "https://www.puntoimpresadigitale.camcom.it/bandi/",
        "https://www.rc.camcom.gov.it/bandi-e-concorsi/bandi-di-gara",
        "https://bandifincalabra.it",
        "https://www.fincalabra.it/web/",
        "https://bandi.contributiregione.it/regione/calabria",
        "https://www.reggiocal.it/Notizie/Details/7541",
        "https://european-union.europa.eu/live-work-study/funding-grants-subsidies_it",
        "https://youreurope.europa.eu/business/finance-funding/getting-funding/access-finance/it",
        "https://www.euipo.europa.eu/it/sme-corner/sme-fund",
        "https://www.invitalia.it",
        "https://commission.europa.eu/funding-tenders/how-apply/eligibility-who-can-get-funding/funding-opportunities-small-businesses_it",
        "https://www.affarieuropei.gov.it/it/attivita/fondi-diretti-europei/come-accedere/",
        "https://uibm.mise.gov.it/index.php/it/al-via-il-fondo-pmi-2025-di-euipo-per-gli-incentivi-europei-in-materia-di-proprieta-industriale",
        "https://www.europainnovazione.com/bandi-europei/"
    ]

    try:
        for sito in SITI_BERSAGLIO:
            print(f"\n{'='*60}\n🌐 INIZIO SCANSIONE PROFONDA: {sito}\n{'='*60}")
            driver = None
            try:
                driver = configura_browser() 
                scansiona_sito_totale(driver, sito)
                print("✅ Sito completato.")
            except Exception as error_sito:
                print(f"⚠️ Errore o timeout sul sito {sito}: {error_sito}")
            finally:
                if driver: 
                    driver.quit() 
                    print("🧹 Browser chiuso, RAM azzerata.")
                    
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
    return "Server Odós Attivo! Prova /avvia-radar"

@app.route('/avvia-radar', methods=['POST', 'GET'])
def api_avvia_radar():
    global RADAR_IN_ESECUZIONE
    
    if RADAR_IN_ESECUZIONE:
        return jsonify({"status": "error", "message": "Il Radar sta già scansionando il web! Attendi."}), 429
    
    thread = threading.Thread(target=avvia_esplorazione_in_background)
    thread.start()
    
    return jsonify({"status": "success", "message": "Radar avviato correttamente in background!"}), 200

if __name__ == "__main__":
    print("🟢 SERVER RADAR ODÓS ACCESO E IN ASCOLTO SULLA PORTA 5000...")
    app.run(host='0.0.0.0', port=5000)
