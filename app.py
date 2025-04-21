from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
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
        resp = requests.get(url, timeout=15)
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
            "url": url,
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
    """Configuration Selenium/Chromium optimisée pour Railway"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Options supplémentaires pour réduire l'utilisation des ressources
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=800,600")
    chrome_options.add_argument("--block-new-web-contents")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
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
    # Augmentation du timeout pour éviter les erreurs
    driver.set_page_load_timeout(120)
    return driver

@app.route('/scrape', methods=['GET'])
def scrape_google_fr():
    """
    Endpoint GET pour scraper Google.fr.
    Version simplifiée pour éviter les timeouts sur Railway.
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        # Aller directement à l'URL de recherche
        driver.get(f"https://www.google.fr/search?q={query}&hl=fr")

        # Attendre que la page se charge avec un timeout plus long
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            logging.warning(f"Timeout lors de l'attente de la page: {str(e)}")
            # Continuer même si le timeout est atteint

        # Un seul scroll léger
        try:
            driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(2)
        except Exception as e:
            logging.warning(f"Erreur lors du scroll: {str(e)}")

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        logging.info("HTML récupéré, extraction des données...")

        # --- PAA
        paa_questions = []
        try:
            question_spans = soup.select('span.CSkcDe')
            paa_questions = [span.get_text(strip=True) for span in question_spans if span.get_text(strip=True)]
            logging.info(f"PAA questions extraites: {len(paa_questions)}")
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction des PAA: {str(e)}")

        # --- Recherches associées
        associated_searches = []
        try:
            assoc_elems = soup.select("div.y6Uyqe div.B2VR9.CJHX3e")
            associated_searches = [elem.get_text(strip=True) for elem in assoc_elems if elem.get_text(strip=True)]
            logging.info(f"Recherches associées extraites: {len(associated_searches)}")
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction des recherches associées: {str(e)}")

        # --- Top 5 (limité à 5 au lieu de 10 pour réduire la charge)
        results = []
        try:
            # Essayer d'abord avec le sélecteur tF2Cxc
            search_elements = soup.select("div.tF2Cxc")
            
            # Si aucun résultat, essayer avec MjjYud
            if not search_elements:
                search_elements = soup.select("div.MjjYud")
            
            # Limiter à 5 résultats
            search_elements = search_elements[:5]
            
            logging.info(f"Éléments de résultats trouvés: {len(search_elements)}")
            
            for result in search_elements:
                try:
                    # Trouver le titre
                    title_elem = result.select_one("h3")
                    google_snippet = title_elem.get_text(strip=True) if title_elem else "Sans titre"
                    
                    # Trouver le lien
                    link_elem = result.select_one("a")
                    link = link_elem["href"] if link_elem and link_elem.has_attr("href") else ""
                    
                    if not link or "google.com" in link:
                        continue
                        
                    domain = urlparse(link).netloc
                    
                    # Analyser la page
                    page_info = analyze_page(link)
                    
                    result_info = {
                        "google_snippet": google_snippet,
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
                    logging.warning(f"Erreur lors de l'analyse d'un résultat: {str(e)}")
                    continue
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction des résultats: {str(e)}")

        # Éviter les doublons entre PAA et recherches associées
        paa_questions = [q for q in paa_questions if q not in associated_searches]

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
            try:
                driver.quit()
                logging.info("Fermeture du navigateur réussie.")
            except Exception as e:
                logging.warning(f"Erreur lors de la fermeture du navigateur: {str(e)}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)