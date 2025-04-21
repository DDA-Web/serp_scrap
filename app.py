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
import re

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
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280x720")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
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

        # Charger Google avec des paramètres spécifiques
        google_url = f"https://www.google.com/search?q={query}&gl=fr&hl=fr&pws=0"
        driver.get(google_url)
        
        # Attendre que la page se charge
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        
        # Pour assurer que tout le contenu est chargé
        time.sleep(2)
        
        # Scroll pour charger plus de contenu
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, 600);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, 900);")
        time.sleep(1)
        
        # Récupérer le HTML complet
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Récupérer tout le texte de la page
        page_text = soup.get_text()
        
        # --- PAA: approche brute mais très robuste - chercher des questions dans le texte complet
        paa_questions = []
        
        # Pattern pour trouver des questions dans le texte (commence par majuscule, se termine par ?)
        question_pattern = re.compile(r'([A-Z][^.!?]*\?)')
        potential_questions = question_pattern.findall(page_text)
        
        for q in potential_questions:
            q = q.strip()
            # Filtrer les questions valides (longueur entre 15 et 150 caractères)
            if 15 <= len(q) <= 150 and not any(q.lower() in existing.lower() for existing in paa_questions):
                paa_questions.append(q)
        
        # --- Associated searches
        associated_searches = []
        
        # Chercher le texte "Recherches associées à"
        related_pattern = re.compile(r'Recherches associées à|Related searches', re.IGNORECASE)
        related_matches = related_pattern.search(page_text)
        
        if related_matches:
            # Prendre tout le texte après "Recherches associées"
            start_index = related_matches.start()
            remaining_text = page_text[start_index:]
            
            # Trouver tous les liens dans cette section avec BeautifulSoup
            related_section = soup.find(string=related_pattern)
            if related_section:
                # Remonter à un parent qui contient des liens
                parent = related_section.parent
                for _ in range(5):  # Remonter jusqu'à 5 niveaux
                    if parent and parent.find_all('a'):
                        break
                    if parent:
                        parent = parent.parent
                
                if parent:
                    # Prendre tous les liens de cette section
                    links = parent.find_all('a')
                    associated_searches = [link.get_text(strip=True) for link in links 
                                          if link.get_text(strip=True) and 3 <= len(link.get_text(strip=True)) <= 100]
        
        # Si on n'a pas trouvé de recherches associées, utiliser une approche plus générique
        if not associated_searches:
            # Récupérer les liens en bas de page qui sont souvent des recherches associées
            all_links = soup.find_all('a')
            # Prendre les liens en bas de page
            bottom_links = all_links[-20:]  # Les 20 derniers liens
            for link in bottom_links:
                text = link.get_text(strip=True)
                if text and 3 <= len(text) <= 100 and not any(word in text.lower() for word in ['google', 'privacy', 'terms']):
                    associated_searches.append(text)
        
        # --- Top 10
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
        
        # Si aucun résultat, essayer d'autres sélecteurs
        if not search_results or len(search_results) < 5:
            search_results = driver.find_elements(By.XPATH, "//div[.//h3]")
        
        results = []
        seen_urls = set()  # Pour éviter les doublons
        
        for element in (search_results[:10] if search_results else []):
            try:
                # Trouver tous les liens dans cet élément
                links = element.find_elements(By.TAG_NAME, "a")
                
                # Trouver un lien valide (non Google)
                link = None
                for l in links:
                    href = l.get_attribute("href")
                    if href and "google.com" not in href and href not in seen_urls:
                        link = href
                        break
                
                if not link:
                    continue
                
                seen_urls.add(link)
                
                # Trouver le titre/snippet
                h3_elements = element.find_elements(By.TAG_NAME, "h3")
                snippet = h3_elements[0].text if h3_elements else "Sans titre"
                
                domain = urlparse(link).netloc
                
                # Analyser la page
                page_info = analyze_page(link)
                
                result_info = {
                    "google_snippet": snippet,
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

        # Limiter le nombre de questions PAA (pour éviter les faux positifs)
        paa_questions = paa_questions[:5] if paa_questions else []

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