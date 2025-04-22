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

# Configuration du logging plus détaillée
logging.basicConfig(
    level=logging.DEBUG,  # Changé à DEBUG pour plus de détails
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Création d'un logger spécifique pour les captchas
captcha_logger = logging.getLogger('captcha_detection')
captcha_logger.setLevel(logging.DEBUG)

def detect_captcha(driver):
    """Détecte la présence d'un captcha sur la page"""
    try:
        # Recherche de signes de captcha
        captcha_indicators = [
            "captcha",
            "recaptcha",
            "challenge",
            "verify you're human",
            "i'm not a robot"
        ]
        
        page_source = driver.page_source.lower()
        for indicator in captcha_indicators:
            if indicator in page_source:
                captcha_logger.warning(f"CAPTCHA DÉTECTÉ: '{indicator}' trouvé dans la page")
                return True
        
        # Vérifie également si le titre de la page contient des signes de captcha
        title = driver.title.lower()
        if any(indicator in title for indicator in captcha_indicators):
            captcha_logger.warning(f"CAPTCHA DÉTECTÉ dans le titre: {driver.title}")
            return True
            
        return False
    except Exception as e:
        captcha_logger.error(f"Erreur lors de la détection de captcha: {str(e)}")
        return False

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
        logging.debug(f"Début de l'analyse de la page: {url}")
        
        resp = requests.get(url, timeout=10)
        logging.debug(f"Réponse HTTP: Status Code {resp.status_code}")
        
        if resp.status_code == 403:
            logging.warning(f"Erreur 403 Forbidden pour {url}")
            
        time.sleep(1)  # On attend un peu (si 403 ou redirect)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # --- Titre de la page
        page_title_tag = soup.find('title')
        page_title = page_title_tag.get_text(strip=True) if page_title_tag else "Aucun <title>"
        logging.debug(f"Titre de la page: {page_title}")

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
        logging.error(traceback.format_exc())
        return {"error": str(e)}

def get_driver():
    """Configuration Selenium/Chromium"""
    logging.info("Création du driver Selenium")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280x720")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
    chrome_options.binary_location = "/usr/bin/chromium"

    service = Service(
        executable_path="/usr/bin/chromedriver",
        service_args=["--verbose"]
    )
    
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(60)
        logging.info("Driver créé avec succès")
        return driver
    except Exception as e:
        logging.error(f"Erreur lors de la création du driver: {str(e)}")
        logging.error(traceback.format_exc())
        raise

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
        logging.warning("Requête reçue sans paramètre 'query'")
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        # Navigation vers Google
        google_url = f"https://www.google.com/search?q={query}&gl=fr"
        logging.info(f"Navigation vers : {google_url}")
        driver.get(google_url)

        # Log de l'URL actuelle après navigation
        logging.info(f"URL actuelle : {driver.current_url}")
        
        # Détection de captcha
        if detect_captcha(driver):
            logging.error("CAPTCHA DÉTECTÉ - Scraping impossible")
            # Capture d'écran pour debug
            try:
                screenshot_path = f"/tmp/captcha_screenshot_{int(time.time())}.png"
                driver.save_screenshot(screenshot_path)
                logging.info(f"Capture d'écran sauvegardée : {screenshot_path}")
            except Exception as e:
                logging.error(f"Impossible de sauvegarder la capture d'écran: {str(e)}")
            
            return jsonify({
                "error": "Captcha détecté - Scraping bloqué",
                "code": 403,
                "details": "Google a détecté une activité automatisée"
            }), 403

        # Attente du chargement de la page
        try:
            WebDriverWait(driver, 30).until(
                lambda d: d.find_element(By.TAG_NAME, "body").text != ""
            )
            logging.info("Page chargée avec succès")
        except Exception as e:
            logging.error(f"Timeout lors du chargement de la page: {str(e)}")
            raise

        time.sleep(3)
        
        # Scroll
        logging.debug("Exécution du scroll")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        html = driver.page_source
        logging.debug(f"HTML récupéré, longueur: {len(html)} caractères")
        
        soup = BeautifulSoup(html, 'html.parser')

        # --- PAA
        paa_questions = [span.get_text(strip=True) for span in soup.select('span.CSkcDe') if span.get_text(strip=True)]
        logging.info(f"PAA trouvées: {len(paa_questions)}")

        # --- Recherches associées
        associated_searches = [elem.get_text(strip=True) for elem in soup.select("div.y6Uyqe div.B2VR9.CJHX3e")]
        logging.info(f"Recherches associées trouvées: {len(associated_searches)}")

        # --- Top 10
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")[:10]
        logging.info(f"Résultats trouvés: {len(search_results)}")
        
        results = []

        for i, element in enumerate(search_results):
            try:
                logging.debug(f"Traitement du résultat {i+1}")
                
                link = element.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                snippet_elem = element.find_element(By.CSS_SELECTOR, "h3, span[role='heading']")
                google_snippet = snippet_elem.text if snippet_elem else "Sans titre"

                domain = urlparse(link).netloc
                logging.debug(f"URL: {link}, Domain: {domain}")

                page_info = analyze_page(link)

                result_info = {
                    "google_snippet": google_snippet,
                    "url": link,  # ➜ Ajout de l'URL complète ici aussi
                    "domain": domain,
                    "page_title": page_info["page_title"],
                    "meta_description": page_info["meta_description"],
                    "headers": page_info["headers"],
                    "word_count": page_info["word_count"],
                    "internal_links": page_info["internal_links"],
                    "external_links": page_info["external_links"],
                    "media": page_info["media"],
                    "structured_data": page_info["structured_data"]
                }
                results.append(result_info)
            except Exception as e:
                logging.warning(f"Élément {i+1} ignoré : {str(e)}")
                logging.debug(traceback.format_exc())
                continue

        response_data = {
            "query": query,
            "paa_questions": paa_questions,
            "associated_searches": associated_searches,
            "results": results
        }
        
        logging.info(f"Scraping terminé avec succès. Résultats: {len(results)}")
        return jsonify(response_data)

    except Exception as e:
        logging.error(f"ERREUR CRITIQUE: {str(e)}")
        logging.error(traceback.format_exc())
        
        # Essaie de capturer une screenshot en cas d'erreur
        if driver:
            try:
                screenshot_path = f"/tmp/error_screenshot_{int(time.time())}.png"
                driver.save_screenshot(screenshot_path)
                logging.info(f"Capture d'écran d'erreur sauvegardée : {screenshot_path}")
                
                # Log du titre et de l'URL actuelle
                logging.error(f"Titre de la page: {driver.title}")
                logging.error(f"URL actuelle: {driver.current_url}")
            except Exception as screenshot_error:
                logging.error(f"Impossible de sauvegarder la capture d'écran: {str(screenshot_error)}")
        
        return jsonify({
            "error": "Service temporairement indisponible",
            "code": 503,
            "details": str(e)
        }), 503

    finally:
        if driver:
            driver.quit()
            logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)