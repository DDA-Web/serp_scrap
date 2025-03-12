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
     - Les entêtes H1 et H2
     - Le nombre de mots
     - Le nombre de liens internes / externes
     - Les médias (images, vidéos, audios, iframes embed)
     - Les données structurées JSON-LD (structured_data)
    """
    try:
        # On peut laisser un petit délai après la requête si nécessaire
        response = requests.get(url, timeout=10)
        time.sleep(1)  # Facultatif, si certaines pages redirigent lentement
        soup = BeautifulSoup(response.text, 'html.parser')

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
            elif link_domain:  # si domain différent et non vide
                external_count += 1

        # --- Médias
        images = len(soup.find_all('img'))
        videos = len(soup.find_all('video'))
        audios = len(soup.find_all('audio'))
        embedded_videos = len(soup.find_all(
            'iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x)
        ))

        # --- Données structurées (JSON-LD)
        structured_data = []
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                json_data = json.loads(script_tag.string)
                structured_data.append(json_data)
            except Exception as e:
                logging.debug(f"Erreur parsing JSON-LD : {e}")
                continue

        return {
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
            "structured_data": structured_data
        }

    except Exception as e:
        logging.error(f"Erreur d'analyse: {str(e)}")
        return {"error": str(e)}

def get_driver():
    """Configuration optimisée de Selenium pour Chromium"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280x720")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
    # Binaire chromium (vérifie sur Railway)
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
    Endpoint pour scraper les résultats Google et analyser chaque page.
    Ex : GET /scrape?query=seo+freelance
    Retourne :
     - query
     - résultats (liste) : domain, title, headers, word_count, internal_links, external_links, media, structured_data
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        # Google France
        driver.get(f"https://www.google.com/search?q={query}&gl=fr")

        # Attendre que le body soit non-vide
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # Récupération des 10 premiers résultats
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.g, div[data-sokoban-container]")[:10]

        results = []
        for element in search_results:
            try:
                link = element.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                title = element.find_element(By.CSS_SELECTOR, "h3, span[role='heading']").text

                # Déterminer le domaine
                domain = urlparse(link).netloc

                # Analyser la page
                page_analysis = analyze_page(link)

                # Construire l'objet "analysis" final tel que souhaité
                analysis = {
                    "domain": domain,
                    "title": title,
                    "headers": page_analysis["headers"],
                    "word_count": page_analysis["word_count"],
                    "internal_links": page_analysis["internal_links"],
                    "external_links": page_analysis["external_links"],
                    "media": page_analysis["media"],
                    "structured_data": page_analysis["structured_data"]
                }

                results.append(analysis)

            except Exception as e:
                logging.warning(f"Élément ignoré : {str(e)}")
                continue

        return jsonify({
            "query": query,
            "results": results
        })

    except Exception as e:
        logging.error(f"ERREUR: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            "error": "Service temporairement indisponible",
            "code": 503
        }), 503

    finally:
        if driver:
            driver.quit()
            logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
