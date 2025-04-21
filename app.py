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
import random

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
        # Ajouter des headers plus convaincants
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.fr/"
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
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
    """Configuration Selenium/Chromium améliorée pour éviter la détection"""
    # Liste de user agents modernes
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ]
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")  # Résolution d'écran standard
    
    # Paramètres de furtivité avancés
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(f"--user-agent={random.choice(user_agents)}")
    
    # Langues et fuseaux horaires réalistes
    chrome_options.add_argument("--lang=fr-FR,fr")
    chrome_options.add_argument("--accept-lang=fr-FR")
    chrome_options.add_argument("--timezone=Europe/Paris")
    
    # Comportement de navigateur standard
    chrome_options.add_argument("--enable-javascript")
    chrome_options.add_argument("--dns-prefetch-disable")
    
    chrome_options.binary_location = "/usr/bin/chromium"

    service = Service(
        executable_path="/usr/bin/chromedriver",
        service_args=["--verbose"]
    )
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Définir des valeurs pour les webdriver properties afin d'éviter la détection
    driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": random.choice(user_agents)})
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            window.chrome = {
                runtime: {}
            };
        """
    })
    
    driver.set_page_load_timeout(90)
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

        # Utiliser Google.fr avec des paramètres spécifiques
        google_url = f"https://www.google.fr/search?q={query}&hl=fr&gl=fr&pws=0"
        logging.info(f"Accès à l'URL: {google_url}")
        driver.get(google_url)

        # Attendre le chargement avec une attente dynamique
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        
        # Ajouter un délai aléatoire pour imiter le comportement humain
        time.sleep(random.uniform(2.5, 4.5))
        
        # Vérifier si un captcha est présent
        if "captcha" in driver.page_source.lower() or "verify you're a human" in driver.page_source.lower():
            logging.warning("CAPTCHA détecté, impossible de continuer")
            return jsonify({"error": "Service temporairement indisponible (CAPTCHA)", "code": 503}), 503

        # Scroll de manière plus humaine (petit à petit)
        for i in range(4):
            driver.execute_script(f"window.scrollTo(0, {(i+1) * 500});")
            time.sleep(random.uniform(0.5, 1.5))
        
        # Remonter un peu
        time.sleep(random.uniform(0.5, 1.5))
        driver.execute_script("window.scrollTo(0, 600);")
        time.sleep(random.uniform(0.5, 1.5))

        # Récupérer le HTML
        html = driver.page_source
        logging.info("HTML récupéré, analyse du contenu...")
        
        # Enregistrer les premiers caractères du HTML pour débugger
        logging.info(f"Début du HTML: {html[:300]}...")
        
        soup = BeautifulSoup(html, 'html.parser')

        # --- 1) PAA Questions
        paa_questions = [span.get_text(strip=True) for span in soup.select('span.CSkcDe') if span.get_text(strip=True)]
        logging.info(f"PAA extraites avec span.CSkcDe: {len(paa_questions)}")
        
        # Si aucune PAA trouvée, essayer d'autres sélecteurs
        if not paa_questions:
            # Essayer d'autres sélecteurs connus pour PAA
            selectors = [
                'div[jsname][role="button"]',  # Sélecteur alternatif 1
                'div.related-question-pair',    # Sélecteur alternatif 2
                'div[data-q]'                  # Sélecteur alternatif 3
            ]
            
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    paa_questions = [elem.get_text(strip=True) for elem in elements 
                                    if elem.get_text(strip=True) and '?' in elem.get_text(strip=True)]
                    logging.info(f"PAA extraites avec {selector}: {len(paa_questions)}")
                    if paa_questions:
                        break

        # --- 2) Recherches associées
        associated_searches = [elem.get_text(strip=True) for elem in soup.select("div.y6Uyqe div.B2VR9.CJHX3e")]
        logging.info(f"Recherches associées extraites: {len(associated_searches)}")
        
        # Si aucune recherche associée trouvée, essayer d'autres sélecteurs
        if not associated_searches:
            # Essayer des sélecteurs alternatifs pour les recherches associées
            alt_selectors = [
                "div.brs_col a",                # Sélecteur alternatif 1
                "div.card-section a",           # Sélecteur alternatif 2
                "div#w3bYAd a"                  # Sélecteur alternatif 3
            ]
            
            for selector in alt_selectors:
                elements = soup.select(selector)
                if elements:
                    associated_searches = [elem.get_text(strip=True) for elem in elements 
                                          if elem.get_text(strip=True) and len(elem.get_text(strip=True)) < 100]
                    logging.info(f"Recherches associées extraites avec {selector}: {len(associated_searches)}")
                    if associated_searches:
                        break

        # --- 3) Top 10 résultats
        results = []
        
        # Essayer d'abord avec le sélecteur original
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
        logging.info(f"Éléments div.MjjYud trouvés: {len(search_results)}")
        
        # Si peu d'éléments trouvés, essayer avec div.tF2Cxc
        if len(search_results) < 5:
            search_results = driver.find_elements(By.CSS_SELECTOR, "div.tF2Cxc")
            logging.info(f"Éléments div.tF2Cxc trouvés: {len(search_results)}")
            
        # Limiter à 10 résultats maximum
        search_results = search_results[:10]

        for element in search_results:
            try:
                # Trouver le lien et le snippet
                link = element.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                snippet_elem = element.find_element(By.CSS_SELECTOR, "h3, span[role='heading']")
                google_snippet = snippet_elem.text if snippet_elem else "Sans titre"

                # Ignorer les liens Google
                if "google.com" in link:
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
                logging.warning(f"Élément ignoré : {str(e)}")
                continue

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
            driver.quit()
            logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)