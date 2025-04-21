from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import requests
import time
import logging
import traceback
from urllib.parse import urlparse
import json

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def analyze_page(url):
    """
    Analyse une page web et retourne :
     - page_title (balise <title>)
     - meta_description (balise <meta name="description">)
     - headers (H1, H2)
     - word_count
     - internal_links, external_links
     - media
     - structured_data (liste des @type des JSON-LD)
    """
    try:
        resp = requests.get(url, timeout=10)
        time.sleep(1)  # On attend un peu (si 403 ou redirect)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # --- Titre de la page
        page_title_tag = soup.find('title')
        page_title = page_title_tag.get_text(strip=True) if page_title_tag else "Aucun <title>"

        # --- Méta description
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        if meta_desc_tag and meta_desc_tag.get("content"):
            meta_description = meta_desc_tag["content"].strip()
        else:
            meta_description = "Aucune meta description"

        # --- H1 / H2
        h1 = soup.find('h1').get_text(strip=True) if soup.find('h1') else "Aucun H1"
        h2s = [tag.get_text(strip=True) for tag in soup.find_all('h2')]

        # --- Nombre de mots
        word_count = len(soup.get_text().split())

        # --- Liens internes / externes
        page_domain = urlparse(url).netloc
        internal_count = 0
        external_count = 0
        links = soup.find_all('a', href=True)
        for link in links:
            link_domain = urlparse(link['href']).netloc
            if link_domain and link_domain == page_domain:
                internal_count += 1
            elif link_domain:
                external_count += 1

        # --- Médias
        images = len(soup.find_all('img'))
        videos = len(soup.find_all('video'))
        audios = len(soup.find_all('audio'))
        embedded_videos = len(soup.find_all(
            'iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x)
        ))

        # --- Données structurées : on ne prend que @type
        structured_data_types = []
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                json_data = json.loads(script_tag.string)
                if isinstance(json_data, dict):
                    schema_type = json_data.get("@type", "Unknown")
                    structured_data_types.append(schema_type)
                elif isinstance(json_data, list):
                    for item in json_data:
                        if isinstance(item, dict):
                            schema_type = item.get("@type", "Unknown")
                            structured_data_types.append(schema_type)
            except Exception as e:
                logging.debug(f"Erreur parsing JSON-LD : {e}")
                continue

        return {
            "url": url,  # ➜ Ajout de l'URL complète
            "page_title": page_title,
            "meta_description": meta_description,
            "headers": {
                "H1": h1,
                "H2": h2s
            },
            "word_count": word_count,
            "internal_links": internal_count,
            "external_links": external_count,
            "media": {
                "images": images,
                "videos": videos,
                "audios": audios,
                "embedded_videos": embedded_videos
            },
            "structured_data": structured_data_types
        }

    except Exception as e:
        logging.error(f"Erreur d'analyse de {url}: {str(e)}")
        return {"error": str(e)}

def get_driver():
    """Configuration Selenium/Chromium"""
    chrome_options = Options()
    
    # Option pour Railway (environnement serveur)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Options communes avec votre script local
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
    chrome_options.binary_location = "/usr/bin/chromium"

    service = Service(
        executable_path="/usr/bin/chromedriver",
        service_args=["--verbose"]
    )
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver

@app.route('/scrape', methods=['GET'])
def scrape_google_fr():
    """
    Endpoint GET pour scraper Google.fr.
    Récupère le top 10, PAA, recherches associées,
    et pour chaque URL : 
      - google_snippet (ce qui vient de la SERP)
      - url
      - domain
      - page_title (de la page)
      - meta_description (de la page)
      - headers (H1, H2)
      - word_count
      - internal_links, external_links
      - media
      - structured_data
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        # Utiliser explicitement Google.fr comme dans votre script local
        driver.get("https://www.google.fr")
        
        # Accepter les cookies (comme dans votre script local)
        try:
            accept_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button#L2AGLb"))
            )
            accept_button.click()
            time.sleep(1)
        except Exception as e:
            logging.info(f"Pas de popup cookies ou déjà accepté: {str(e)}")
        
        # Saisir la requête comme dans votre script local
        search_box = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.NAME, "q"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)
        
        # Attendre que les résultats soient chargés, en ciblant spécifiquement div.tF2Cxc
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.tF2Cxc"))
            )
        except:
            # Fallback si div.tF2Cxc n'est pas trouvé
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.MjjYud"))
            )

        # Scroll pour charger tout le contenu
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(1)

        # Récupérer le HTML et le parser
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Log de debug pour voir les classes disponibles
        logging.info(f"Classes disponibles (span): {[elem.get('class') for elem in soup.select('span') if elem.get('class')][:5]}")
        logging.info(f"Classes disponibles (div): {[elem.get('class') for elem in soup.select('div') if elem.get('class')][:5]}")

        # --- 1) Extraction des PAA (People Also Ask) ---
        #    Exactement comme dans votre script local
        paa_questions = []
        question_spans = soup.select('span.CSkcDe')
        logging.info(f"Nombre de spans PAA trouvés: {len(question_spans)}")
        for span in question_spans:
            text = span.get_text(strip=True)
            if text:
                paa_questions.append(text)

        # --- 2) Extraction des recherches associées ---
        #    Exactement comme dans votre script local
        assoc_elems = soup.select("div.y6Uyqe div.B2VR9.CJHX3e")
        logging.info(f"Nombre d'éléments de recherches associées trouvés: {len(assoc_elems)}")
        associated_searches = [elem.get_text(strip=True) for elem in assoc_elems if elem.get_text(strip=True)]

        # --- 3) Extraction du Top 10 ---
        #    Utiliser d'abord div.tF2Cxc comme dans votre script local
        results_elements = soup.select("div.tF2Cxc")
        logging.info(f"Nombre d'éléments div.tF2Cxc trouvés: {len(results_elements)}")
        
        # Si peu d'éléments trouvés, essayer avec le sélecteur MjjYud
        if len(results_elements) < 5:
            results_elements = soup.select("div.MjjYud")
            logging.info(f"Fallback : Nombre d'éléments div.MjjYud trouvés: {len(results_elements)}")
        
        # Limiter aux 10 premiers résultats
        results_elements = results_elements[:10]
        
        results = []
        for i, result in enumerate(results_elements, start=1):
            try:
                # Trouver le titre et le lien (comme dans votre script local)
                title_elem = result.select_one("h3")
                title = title_elem.get_text(strip=True) if title_elem else "Sans titre"
                
                link_elem = result.select_one("a")
                link = link_elem["href"] if link_elem and link_elem.has_attr("href") else ""
                
                if not link or "google.com" in link:
                    continue
                    
                domain = urlparse(link).netloc

                # Analyser la page
                page_info = analyze_page(link)

                result_info = {
                    "google_snippet": title,
                    "url": link,
                    "domain": domain,
                    "page_title": page_info.get("page_title", ""),
                    "meta_description": page_info.get("meta_description", ""),
                    "headers": page_info.get("headers", {"H1": "", "H2": []}),
                    "word_count": page_info.get("word_count", 0),
                    "internal_links": page_info.get("internal_links", 0),
                    "external_links": page_info.get("external_links", 0),
                    "media": page_info.get("media", {}),
                    "structured_data": page_info.get("structured_data", [])
                }
                results.append(result_info)
            except Exception as e:
                logging.warning(f"Élément ignoré : {str(e)}")
                continue

        # Éviter les doublons entre PAA et recherches associées
        paa_questions = [q for q in paa_questions if q not in associated_searches]

        # Log final pour diagnostiquer les résultats
        logging.info(f"PAA questions: {len(paa_questions)}")
        logging.info(f"Recherches associées: {len(associated_searches)}")
        logging.info(f"Résultats: {len(results)}")

        return jsonify({
            "query": query,
            "paa_questions": paa_questions,
            "associated_searches": associated_searches,
            "results": results
        })

    except Exception as e:
        logging.error(f"ERREUR: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Service temporairement indisponible", "code": 503}), 503

    finally:
        if driver:
            driver.quit()
            logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)