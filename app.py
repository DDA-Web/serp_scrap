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
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver

def find_paa_questions(soup):
    """
    Fonction robuste pour trouver les PAA questions avec plusieurs sélecteurs possibles
    """
    paa_questions = []
    
    # Première méthode - sélecteur actuel
    paa_spans = soup.select('span.CSkcDe')
    if paa_spans:
        paa_questions = [span.get_text(strip=True) for span in paa_spans if span.get_text(strip=True)]
    
    # Deuxième méthode - recherche par le texte "Les internautes ont également demandé"
    if not paa_questions:
        for heading in soup.find_all(['h2', 'h3']):
            if "internautes ont également demandé" in heading.get_text().lower():
                # Récupérer les questions dans le bloc
                container = heading.parent
                for i in range(3):  # Chercher dans les parents si nécessaire
                    if container:
                        questions = container.find_all(['div', 'span'], class_=lambda c: c and (
                            'question' in c.lower() or 'accordion' in c.lower()))
                        if questions:
                            paa_questions = [q.get_text(strip=True) for q in questions if q.get_text(strip=True)]
                            break
                        container = container.parent
    
    # Troisième méthode - recherche par structure (éléments cliquables)
    if not paa_questions:
        accordion_elements = soup.find_all(['div', 'span'], attrs={'role': 'button'})
        if accordion_elements:
            paa_candidates = []
            for elem in accordion_elements:
                text = elem.get_text(strip=True)
                if text and 5 <= len(text) <= 200 and text.endswith('?'):
                    paa_candidates.append(text)
            if paa_candidates:
                paa_questions = paa_candidates
    
    return paa_questions

def find_associated_searches(soup):
    """
    Fonction robuste pour trouver les recherches associées avec plusieurs sélecteurs possibles
    """
    searches = []
    
    # Première méthode - sélecteur actuel
    searches_elements = soup.select("div.y6Uyqe div.B2VR9.CJHX3e")
    if searches_elements:
        searches = [elem.get_text(strip=True) for elem in searches_elements]
    
    # Deuxième méthode - recherche par le texte "Recherches associées à"
    if not searches:
        for heading in soup.find_all(['h2', 'h3', 'div']):
            heading_text = heading.get_text().lower()
            if "recherches associées" in heading_text or "related searches" in heading_text:
                container = heading.parent
                for i in range(3):  # Chercher dans les parents si nécessaire
                    if container:
                        links = container.find_all('a')
                        if links:
                            search_candidates = []
                            for link in links:
                                text = link.get_text(strip=True)
                                if text and 3 <= len(text) <= 100:
                                    search_candidates.append(text)
                            if search_candidates:
                                searches = search_candidates
                                break
                        container = container.parent
    
    # Troisième méthode - chercher en bas de page les liens après le numéro de page
    if not searches:
        pagination = soup.find_all('a', string=lambda s: s and s.isdigit())
        if pagination:
            last_pagination = pagination[-1]
            parent_container = last_pagination.parent
            while parent_container and len(parent_container.find_all('a')) < 5:
                parent_container = parent_container.parent
            
            if parent_container:
                # Chercher les liens après la pagination
                next_sibling = parent_container.next_sibling
                while next_sibling and not searches:
                    links = next_sibling.find_all('a')
                    if links:
                        searches = [link.get_text(strip=True) for link in links 
                                  if link.get_text(strip=True) and 3 <= len(link.get_text(strip=True)) <= 100]
                    next_sibling = next_sibling.next_sibling
    
    return searches

def find_search_results(driver, soup):
    """
    Fonction robuste pour trouver les résultats de recherche avec plusieurs sélecteurs possibles
    """
    results_list = []
    
    # Première méthode - sélecteur actuel
    search_results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
    if search_results and len(search_results) >= 5:  # Vérifier qu'on a bien des résultats (au moins 5)
        results_list = search_results[:10]
    
    # Deuxième méthode - chercher les éléments avec des titres et des liens
    if not results_list or len(results_list) < 5:
        search_results = driver.find_elements(By.CSS_SELECTOR, "div[data-sokoban-container]")
        if search_results and len(search_results) >= 5:
            results_list = search_results[:10]
    
    # Troisième méthode - chercher les noeuds <a> avec des titres
    if not results_list or len(results_list) < 5:
        search_results = driver.find_elements(By.XPATH, "//a[.//h3]")
        if search_results and len(search_results) >= 5:
            # Pour chaque lien avec un h3, on récupère son parent
            results_list = []
            for result in search_results[:10]:
                parent = driver.execute_script("""
                    var element = arguments[0];
                    var currentParent = element.parentElement;
                    while (currentParent && currentParent.querySelectorAll('a').length < 3) {
                        currentParent = currentParent.parentElement;
                    }
                    return currentParent;
                """, result)
                if parent and parent not in results_list:
                    results_list.append(parent)
    
    # Si on n'a toujours pas de résultats, on peut essayer une approche plus générique
    if not results_list or len(results_list) < 5:
        # Récupérer tous les liens qui ne sont pas des liens de navigation/pagination
        all_links = driver.find_elements(By.XPATH, "//a[@href and not(contains(@href, '#')) and string-length(.) > 10]")
        results_seen = set()
        results_list = []
        
        for link in all_links:
            try:
                href = link.get_attribute("href")
                if href and "google.com" not in href and href not in results_seen:
                    parent = driver.execute_script("""
                        var element = arguments[0];
                        var currentParent = element.parentElement;
                        while (currentParent && currentParent.tagName != 'BODY' && 
                               currentParent.offsetHeight < 100) {
                            currentParent = currentParent.parentElement;
                        }
                        return currentParent && currentParent.tagName != 'BODY' ? currentParent : null;
                    """, link)
                    
                    if parent and parent not in results_list:
                        results_list.append(parent)
                        results_seen.add(href)
                        
                        if len(results_list) >= 10:
                            break
            except:
                continue
    
    return results_list[:10]  # Limiter à 10 résultats

def extract_search_result_info(element, driver):
    """
    Extrait les informations d'un élément de résultat de recherche de manière robuste
    """
    try:
        # Essayer plusieurs méthodes pour trouver le lien
        link = None
        
        # Méthode 1: chercher un lien avec un h3
        link_with_h3 = element.find_elements(By.XPATH, ".//a[.//h3]")
        if link_with_h3:
            link = link_with_h3[0].get_attribute("href")
        
        # Méthode 2: chercher un lien avec un rôle de titre
        if not link:
            link_with_heading = element.find_elements(By.XPATH, ".//a[.//span[@role='heading']]")
            if link_with_heading:
                link = link_with_heading[0].get_attribute("href")
        
        # Méthode 3: chercher le premier lien significatif
        if not link:
            links = element.find_elements(By.XPATH, ".//a[@href and not(contains(@href, '#'))]")
            for l in links:
                href = l.get_attribute("href")
                if href and "google.com" not in href:
                    link = href
                    break
        
        if not link:
            return None
        
        # Essayer plusieurs méthodes pour trouver le snippet
        google_snippet = "Sans titre"
        
        # Méthode 1: chercher un h3
        h3_element = element.find_elements(By.TAG_NAME, "h3")
        if h3_element:
            google_snippet = h3_element[0].text
        
        # Méthode 2: chercher un span avec rôle de titre
        if google_snippet == "Sans titre":
            heading_span = element.find_elements(By.XPATH, ".//span[@role='heading']")
            if heading_span:
                google_snippet = heading_span[0].text
        
        # Méthode 3: chercher le texte du lien principal
        if google_snippet == "Sans titre" and (link_with_h3 or link_with_heading):
            main_link = link_with_h3[0] if link_with_h3 else link_with_heading[0]
            if main_link:
                google_snippet = main_link.text
        
        domain = urlparse(link).netloc
        
        return {
            "google_snippet": google_snippet.strip() if google_snippet else "Sans titre",
            "url": link,
            "domain": domain
        }
    except Exception as e:
        logging.warning(f"Erreur lors de l'extraction des informations de résultat: {str(e)}")
        return None

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

        driver.get(f"https://www.google.com/search?q={query}&gl=fr&hl=fr")

        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        
        # Scroll down to make sure everything is loaded
        for _ in range(3):  # Scroll progressivement pour charger tout le contenu
            driver.execute_script("window.scrollTo(0, window.scrollY + 500);")
            time.sleep(0.7)
        
        # Accepter les cookies si nécessaire
        try:
            cookie_buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Accept') or contains(., 'Accepter')]")
            if cookie_buttons:
                cookie_buttons[0].click()
                time.sleep(1)
        except:
            pass
            
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # --- PAA avec méthode robuste
        paa_questions = find_paa_questions(soup)
        
        # --- Recherches associées avec méthode robuste
        associated_searches = find_associated_searches(soup)
        
        # --- Top 10 avec méthode robuste
        search_results = find_search_results(driver, soup)
        results = []

        for element in search_results:
            try:
                result_info = extract_search_result_info(element, driver)
                if result_info and result_info["url"]:
                    # Analyser la page
                    page_info = analyze_page(result_info["url"])
                    
                    # Fusionner les informations
                    full_result = {
                        **result_info,
                        "page_title": page_info.get("page_title", ""),
                        "meta_description": page_info.get("meta_description", ""),
                        "headers": page_info.get("headers", {"H1": "", "H2": []}),
                        "word_count": page_info.get("word_count", 0),
                        "internal_links": page_info.get("internal_links", 0),
                        "external_links": page_info.get("external_links", 0),
                        "media": page_info.get("media", {}),
                        "structured_data": page_info.get("structured_data", [])
                    }
                    results.append(full_result)
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
        return jsonify({"error": "Service temporairement indisponible", "code": 503}), 503

    finally:
        if driver:
            driver.quit()
            logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)