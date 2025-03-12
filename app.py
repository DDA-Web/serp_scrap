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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def analyze_page(url):
    """Analyse une page web et retourne ses métriques SEO : 
       - Type de contenu (Article, Page de service, Comparateur, Autre)
       - Structure Hn (H1 et H2s)
       - Nombre de mots
       - Nombre de liens internes/externes
       - Médias présents (images, vidéos, audios, iframes embed)
    """
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Détection du type de page
        page_type = "Autre"
        if soup.find('article'):
            page_type = 'Article'
        elif soup.find('section') and 'service' in response.text.lower():
            page_type = 'Page de service'
        elif 'comparateur' in response.text.lower():
            page_type = 'Comparateur'

        # Extraction des headers
        h1 = soup.find('h1').get_text().strip() if soup.find('h1') else "Aucun H1"
        h2s = [tag.get_text().strip() for tag in soup.find_all('h2')]

        # Comptage des mots
        word_count = len(soup.get_text().split())

        # Liens internes et externes
        links = soup.find_all('a', href=True)
        internal_links = [link['href'] for link in links if url in link['href']]
        external_links = [link['href'] for link in links if url not in link['href']]

        # Médias présents
        images = len(soup.find_all('img'))
        videos = len(soup.find_all('video'))
        audios = len(soup.find_all('audio'))
        embedded_videos = len(soup.find_all(
            'iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x)
        ))

        return {
            "type": page_type,
            "headers": {"H1": h1, "H2": h2s},
            "word_count": word_count,
            "internal_links": len(internal_links),
            "external_links": len(external_links),
            "media": {
                "images": images,
                "videos": videos,
                "audios": audios,
                "embedded_videos": embedded_videos
            }
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
    # Chemin binaire de Chromium (vérifie que c'est correct sur Railway)
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
    """Endpoint GET pour scraper Google.fr.
       Récupère le top 10, PAA (People Also Ask) et les recherches associées.
       Exemple d'appel : GET /scrape?query=seo+freelance
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        # On cible Google France (paramètre &gl=fr pour forcer FR)
        driver.get(f"https://www.google.com/search?q={query}&gl=fr")

        # Attendre que le body soit non-vide
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        time.sleep(3)

        # Scroll basique
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # Récupérer le HTML complet pour extraire PAA et recherches associées
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # PAA (People Also Ask)
        paa_questions = []
        paa_spans = soup.select('span.CSkcDe')
        for span in paa_spans:
            question_text = span.get_text(strip=True)
            if question_text:
                paa_questions.append(question_text)

        # Recherches associées
        associated_searches = []
        assoc_elems = soup.select("div.y6Uyqe div.B2VR9.CJHX3e")
        for elem in assoc_elems:
            txt = elem.get_text(strip=True)
            if txt:
                associated_searches.append(txt)

        # Récupérer le top 10 (div.g ou div[data-sokoban-container])
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.g, div[data-sokoban-container]")[:10]

        results = []
        for element in search_results:
            try:
                link = element.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                title = element.find_element(By.CSS_SELECTOR, "h3, span[role='heading']").text
                analysis = analyze_page(link)
                results.append({
                    "title": title,
                    "link": link,
                    "analysis": analysis
                })
            except Exception as e:
                logging.warning(f"Élément ignoré : {str(e)}")
                continue

        return jsonify({
            "query": query,
            "paa_questions": paa_questions,
            "associated_searches": associated_searches,
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
