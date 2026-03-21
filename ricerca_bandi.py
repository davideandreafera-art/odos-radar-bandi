import sys
import time
import json
import os
import requests
import urllib3
import PyPDF2
import threading # 👈 Il trucco per lavorare in background
from urllib.parse import urljoin, urlparse
from google import genai

# Nuove librerie per creare il Server Web
from flask import Flask, jsonify
from flask_cors import CORS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# =================================================================
# 1. CONFIGURAZIONE ASSOLUTA
# =================================================================
CHIAVE_GOOGLE = "AIzaSyAEn9vpmSXwFthCJFKk3842q_nGFp0ZKMY" # 👈 La tua API Key!
client = genai.Client(api_key=CHIAVE_GOOGLE)

URL_GESTIONALE = "https://www.studioodos.it/api_bandi_sync.php?token=ODOS_PYTHON_GEMINI_SYNC_2026"

PAROLE_CHIAVE = ['bando', 'avvisi', 'avviso', 'agevolazione', 'finanziamento', 'contributo', 'voucher', 'pid']

# Inizializziamo il Server Flask
app = Flask(__name__)
CORS(app) # Permette al tuo sito PHP di parlare con questo server

# Variabile di sicurezza per evitare che si aprano 100 Chrome se si clicca 100 volte
RADAR_IN_ESECUZIONE = False

# =================================================================
# 2. MOTORE DEL BROWSER E LETTURA PDF (Rimasti identici)
# =================================================================
def configura_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def estrai_testo_da_pdf_online(url_pdf):
    print(f"   📄 Estrazione da: {url_pdf[:70]}...")
    nome_file_temp = "temp_bando.pdf"
    try:
        risposta = requests.get(url_pdf, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=15, verify=False)
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
            if "429" in str(e):
                print(f"   ⏳ Ops, Google in attesa (Tentativo {tentativo+1}/{massimo_tentativi}). Pausa 60s...")
                time.sleep(60)
            else:
                print(f"   ⚠️ Errore lettura IA: {e}")
                break

# =================================================================
# 3. LO SMART SPIDER
# =================================================================
def scansiona_sito_totale(driver, url_partenza):
    dominio_base = urlparse(url_partenza).netloc
    link_visitati = set()
    link_da_visitare = [url_partenza]
    pdf_trovati_e_analizzati = set()
    
    LIMITE_PAGINE_WEB = 15
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
            time.sleep(3) 
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
            print(f"   ⚠️ Errore navigando su {url_corrente} | DETTAGLIO: {e}")

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
        "https://www.reggiocal.it/Notizie/Details/7541"
    ]

    try:
        driver = configura_browser()
        for sito in SITI_BERSAGLIO:
            print(f"\n{'='*60}\n🌐 INIZIO SCANSIONE PROFONDA: {sito}\n{'='*60}")
            scansiona_sito_totale(driver, sito)
            print("✅ Sito completato.")
    except Exception as e:
        print(f"🆘 Errore Critico: {str(e)}")
    finally:
        print("\nChiudo i motori del browser...")
        if 'driver' in locals(): driver.quit()
        RADAR_IN_ESECUZIONE = False
        print("🏁 Scansione Totale Terminata. Pronto per il prossimo comando.")

# =================================================================
# 5. LE ROTTE FLASK (L'orecchio del Server)
# =================================================================
@app.route('/')
def home():
    return "Server Odós Attivo! Prova /avvia-radar"
@app.route('/avvia-radar', methods=['POST', 'GET'])
def api_avvia_radar():
    global RADAR_IN_ESECUZIONE
    
    # Controllo di sicurezza: sta già girando?
    if RADAR_IN_ESECUZIONE:
        return jsonify({"status": "error", "message": "Il Radar sta già scansionando il web! Attendi."}), 429
    
    # Crea un nuovo "Filo" (Thread) per far lavorare il robot in background
    thread = threading.Thread(target=avvia_esplorazione_in_background)
    thread.start()
    
    # Risponde IMMEDIATAMENTE al tuo sito PHP, senza aspettare che finisca!
    return jsonify({"status": "success", "message": "Radar avviato correttamente in background!"}), 200

# =================================================================
# 🚀 AVVIO DEL SERVER
# =================================================================
if __name__ == "__main__":
    print("🟢 SERVER RADAR ODÓS ACCESO E IN ASCOLTO SULLA PORTA 5000...")
    # Avvia il server web in locale sulla porta 5000
    app.run(host='0.0.0.0', port=5000)
