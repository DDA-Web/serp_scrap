from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from bs4 import BeautifulSoup
import requests
import time
import json

app = Flask(__name__)

def analyze_page(url):
    """
    Analyse le contenu d'une URL donnée et retourne un dictionnaire contenant :
      - Le type de page (Article, Page de service, Comparateur, Autre)
      - Les entêtes H1 et H2
      - Le nombre de mots
      - Le nombre de liens internes et externes
      - Le nombre d'images, vidéos, audios, vidéos embed
      - Les types de données structurées (JSON-LD)
    """
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Type de page
        if soup.find('article'):
            page_type = 'Article'
        elif soup.find('section') and 'service' in response.text.lower():
            page_type = 'Page de service'
        elif 'comparateur' in response.text.lower():
            page_type = 'Comparateur'
        else:
            page_type = 'Autre'

        # 2. Structure HN
        h1 = soup.find('h1').text.strip() if soup.find('h1') else "Aucun H1"
        h2s = [tag.get_text(strip=True) for tag in soup.find_all('h2')]
        headers = {'H1': h1, 'H2': h2s}

        # 3. Nombre de mots
        words = len(soup.get_text().split())

        # 4. Liens internes / externes
        links = soup.find_all('a', href=True)
        internal_links = [link['href'] for link in links if url in link['href']]
        external_links = [link['href'] for link in links if url not in link['href']]

        # 5. Médias
        images = len(soup.find_all('img'))
        videos = len(soup.find_all('video'))
        audios = len(soup.find_all('audio'))
        embedded_videos = len(soup.find_all(
            'iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x)
        ))

        # 6. Données structurées JSON-LD
        structured_data_types = []
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                json_data = json.loads(script_tag.string)
                if isinstance(json_data, list):
                    for item in json_data:
                        if isinstance(item, dict) and "@type" in item:
                            structured_data_types.append(item["@type"])
                elif isinstance(json_data, dict):
                    if "@type" in json_data:
                        structured_data_types.append(json_data["@type"])
            except Exception:
                continue

        return {
            'type': page_type,
            'headers': headers,
            'word_count': words,
            'internal_links': len(internal_links),
            'external_links': len(external_links),
            'media': {
                'images': images,
                'videos': videos,
                'audios': audios,
                'embedded_videos': embedded_videos
            },
            'structured_data_types': structured_data_types
        }
    except Exception as e:
        return {'error': str(e)}

def google_scraper(query):
    """
    Lance une recherche Google via Selenium (Chrome headless) et renvoie :
      - La liste des questions "People Also Ask" (PAA)
      - Les recherches associées
      - Le Top 10 des résultats : domaine, lien, titre et analyse de page
    """
    chrome_options = Options()
    # Arguments recommandés pour l'exécution dans un conteneur
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )

    try:
        driver.get("https://www.google.fr")

        # Accepter les cookies si le bouton apparaît
        try:
            accept_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button#L2AGLb"))
            )
            accept_button.click()
        except:
            pass

        # Saisir la requête et valider
        search_box = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.NAME, "q"))
        )
        search_box.send_keys(query + Keys.RETURN)

        # Attendre que les résultats soient chargés
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.tF2Cxc"))
        )
        time.sleep(1)

        # Récupérer le HTML complet
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # 1) Extraction des PAA (People Also Ask)
        paa_questions = []
        question_spans = soup.select('span.CSkcDe')
        for span in question_spans:
            text = span.get_text(strip=True)
            if text:
                paa_questions.append(text)

        # 2) Extraction des recherches associées
        assoc_elems = soup.select("div.y6Uyqe div.B2VR9.CJHX3e")
        associated_searches = [elem.get_text(strip=True) for elem in assoc_elems if elem.get_text(strip=True)]

        # 3) Extraction du Top 10
        results = soup.select("div.tF2Cxc")
        top_10_data = []
        for i, result in enumerate(results[:10], start=1):
            try:
                title_elem = result.select_one("h3")
                title = title_elem.get_text(strip=True) if title_elem else "Sans titre"

                link_elem = result.select_one("a")
                link = link_elem["href"] if link_elem else "#"
                domain = link.split("/")[2] if link.startswith("http") else "N/A"

                # Analyse de la page
                analysis = analyze_page(link)

                top_10_data.append({
                    "rank": i,
                    "domain": domain,
                    "link": link,
                    "title": title,
                    "analysis": analysis
                })
            except Exception as e:
                # On ignore l'erreur pour cet élément et on passe au suivant
                print(f"Erreur sur un résultat : {e}")

        return {
            "paa_questions": paa_questions,
            "associated_searches": associated_searches,
            "top_10_data": top_10_data
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        driver.quit()

@app.route('/analyze', methods=['POST'])
def analyze_endpoint():
    """
    Endpoint pour analyser le contenu d'une page.
    Requête JSON attendue : { "url": "https://exemple.com" }
    """
    data = request.get_json()
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "Merci de fournir un paramètre 'url'"}), 400

    result = analyze_page(url)
    return jsonify(result)

@app.route('/scrape_google', methods=['POST'])
def scrape_google_endpoint():
    """
    Endpoint pour lancer une recherche Google.
    Requête JSON attendue : { "query": "votre requête de recherche" }
    """
    data = request.get_json()
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "Merci de fournir un paramètre 'query'"}), 400

    result = google_scraper(query)
    return jsonify(result)

# Point d'entrée principal pour Gunicorn
if __name__ == "__main__":
    # Lancement du serveur Flask en local (pour debug)
    # En production, c'est Gunicorn (cf. CMD dans Dockerfile) qui sert l'appli.
    app.run(host="0.0.0.0", port=8000)
