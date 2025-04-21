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

        # Désactiver JavaScript pour plus de stabilité
        driver.execute_cdp_cmd("Emulation.setScriptExecutionDisabled", {"value": True})
        
        # Charger Google avec des paramètres spécifiques
        driver.get(f"https://www.google.com/search?q={query}&gl=fr&hl=fr&pws=0")

        # Attendre que la page se charge
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        
        # Réactiver JavaScript et recharger la page
        driver.execute_cdp_cmd("Emulation.setScriptExecutionDisabled", {"value": False})
        driver.refresh()
        time.sleep(3)
        
        # Scroll pour charger plus de contenu
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, window.scrollY + 1000);")
            time.sleep(1)
        
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extraction brute de tous les éléments de texte
        full_text = soup.get_text()
        
        # --- PAA: approche basée sur le texte brut de la page
        paa_questions = []
        
        # Utiliser XPath pour cibler directement les éléments PAA
        paa_elements = driver.find_elements(By.XPATH, "//div[@jsname]//div[@role='button']")
        for elem in paa_elements:
            text = elem.text.strip()
            if text and text.endswith('?') and len(text) > 10 and len(text) < 200:
                paa_questions.append(text)
        
        # Si aucun PAA n'a été trouvé via XPath, chercher dans le texte
        if not paa_questions:
            # Recherche de questions dans le texte brut
            potential_questions = re.findall(r'([A-Z][^.!?]*\?)', full_text)
            for q in potential_questions:
                q = q.strip()
                if 10 < len(q) < 200 and q not in paa_questions:
                    paa_questions.append(q)
        
        # --- Recherches associées: approche basée sur le texte et structure
        associated_searches = []
        
        # Chercher d'abord par XPath les éléments de recherches associées
        try:
            # Trouver le bloc de recherches associées
            related_blocks = driver.find_elements(By.XPATH, "//div[contains(., 'Recherches associées') or contains(., 'Related searches')]")
            
            if related_blocks:
                # Trouver le bloc parent qui contient les liens
                for block in related_blocks:
                    parent_element = driver.execute_script("""
                        var element = arguments[0];
                        var parent = element.parentElement;
                        while (parent && parent.tagName !== 'BODY' && parent.querySelectorAll('a').length < 3) {
                            parent = parent.parentElement;
                        }
                        return parent;
                    """, block)
                    
                    if parent_element:
                        # Récupérer tous les liens dans ce bloc
                        related_links = parent_element.find_elements(By.TAG_NAME, "a")
                        for link in related_links:
                            text = link.text.strip()
                            if text and len(text) > 3 and len(text) < 100:
                                associated_searches.append(text)
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction des recherches associées par XPath: {str(e)}")
        
        # Si aucune recherche associée n'a été trouvée, utiliser BeautifulSoup
        if not associated_searches:
            # Chercher toutes les sections qui pourraient contenir "Recherches associées"
            for section in soup.find_all(['div', 'span']):
                if 'recherches associées' in section.get_text().lower():
                    # Trouver tous les liens dans cette section et les sections suivantes
                    current = section
                    for _ in range(5):  # Vérifier 5 sections
                        if current:
                            links = current.find_all('a')
                            for link in links:
                                text = link.get_text(strip=True)
                                if text and 3 < len(text) < 100 and text not in associated_searches:
                                    associated_searches.append(text)
                            current = current.find_next_sibling()
        
        # Approche de dernier recours pour les recherches associées
        if not associated_searches:
            # Chercher tous les liens en bas de page qui ont un texte court
            all_links = soup.find_all('a')
            
            # Filtrer les derniers liens qui pourraient être des recherches associées
            bottom_links = all_links[-15:]  # Prendre les 15 derniers liens
            for link in bottom_links:
                text = link.get_text(strip=True)
                if text and 3 < len(text) < 100 and text not in associated_searches:
                    associated_searches.append(text)
        
        # --- Top 10
        search_results = []
        
        # Approche 1: utiliser les sélecteurs CSS standard
        elements = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
        if elements and len(elements) >= 5:
            search_results = elements[:10]
        
        # Approche 2: chercher les blocs avec des titres et des liens
        if not search_results or len(search_results) < 5:
            elements = driver.find_elements(By.XPATH, "//div[.//h3 and .//a/@href]")
            if elements and len(elements) >= 5:
                search_results = elements[:10]
        
        # Approche 3: chercher directement les liens avec des titres
        if not search_results or len(search_results) < 5:
            elements = driver.find_elements(By.XPATH, "//a[.//h3 or .//*[@role='heading']]")
            if elements and len(elements) >= 5:
                search_results = elements[:10]
        
        results = []
        for element in search_results:
            try:
                # Trouver le lien
                link_element = None
                try:
                    link_element = element.find_element(By.XPATH, ".//a[.//h3]")
                except:
                    try:
                        link_element = element.find_element(By.XPATH, ".//a[.//*[@role='heading']]")
                    except:
                        try:
                            link_element = element.find_element(By.TAG_NAME, "a")
                        except:
                            continue
                
                link = link_element.get_attribute("href")
                if not link or "google.com" in link:
                    continue
                
                # Trouver le snippet
                title_element = None
                try:
                    title_element = element.find_element(By.TAG_NAME, "h3")
                except:
                    try:
                        title_element = element.find_element(By.XPATH, ".//*[@role='heading']")
                    except:
                        title_element = link_element
                
                snippet = title_element.text if title_element else "Sans titre"
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