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

def get_driver():
    """Configuration Selenium (Chromium headless)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280x720")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.binary_location = "/usr/bin/chromium"   # Chemin de chromium
    service = Service("/usr/bin/chromedriver")             # Chemin de chromedriver

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver

def analyze_page(url):
    """Analyse la page en HTTP (requests + BeautifulSoup), renvoie quelques métriques SEO."""
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Type de page
        page_type = "Autre"
        if soup.find('article'):
            page_type = 'Article'
        elif soup.find('section') and 'service' in resp.text.lower():
            page_type = 'Page de service'
        elif 'comparateur' in resp.text.lower():
            page_type = 'Comparateur'

        # 2. H1 / H2
        h1 = soup.find('h1').get_text(strip=True) if soup.find('h1') else "Aucun H1"
        h2s = [tag.get_text(strip=True) for tag in soup.find_all('h2')]

        # 3. Word count
        word_count = len(soup.get_text().split())

        # 4. Liens internes / externes
        links = soup.find_all('a', href=True)
        internal_links = [link['href'] for link in links if url in link['href']]
        external_links = [link['href'] for link in links if url not in link['href']]

        # 5. Médias
        images = len(soup.find_all('img'))
        videos = len(soup.find_all('video'))
        audios = len(soup.find_all('audio'))
        embedded = len(soup.find_all('iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x)))

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
                "embedded_videos": embedded
            }
        }

    except Exception as e:
        logging.error(f"Erreur analyze_page : {str(e)}")
        return {"error": str(e)}

@app.route('/scrape', methods=['GET'])
def scrape_google():
    """
    GET /scrape?query=exemple
    Récupère PAA, recherches associées, et le top 10 (avec analyse de page).
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Scraping pour la requête: {query}")
        driver = get_driver()

        # Charger Google.fr, paramètre gl=fr pour cibler la France
        driver.get(f"https://www.google.fr/search?q={query}&gl=fr")

        # Attendre que le contenu principal se charge
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.tF2Cxc, div.g"))
        )
        time.sleep(1)

        # Récupérer le HTML avec BeautifulSoup
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

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

        # Top 10
        results_divs = soup.select("div.tF2Cxc, div.g")
        top10 = []
        count = 0
        for div in results_divs:
            if count >= 10:
                break
            # Certains blocs 'div.g' n'ont pas toujours un <a> avec un h3
            link_elem = div.select_one("a")
            title_elem = div.select_one("h3")
            if link_elem and title_elem:
                link = link_elem.get("href", "#")
                title = title_elem.get_text(strip=True) or "Sans titre"
                analysis = analyze_page(link)

                top10.append({
                    "rank": count + 1,
                    "link": link,
                    "title": title,
                    "analysis": analysis
                })
                count += 1

        return jsonify({
            "query": query,
            "paa_questions": paa_questions,
            "associated_searches": associated_searches,
            "top_10_data": top10
        })

    except Exception as e:
        logging.error(f"ERREUR : {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Erreur interne", "details": str(e)}), 500

    finally:
        if driver:
            driver.quit()
            logging.info("Fermeture du navigateur")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
