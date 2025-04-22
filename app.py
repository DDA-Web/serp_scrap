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
import undetected_chromedriver as uc
import os
import concurrent.futures
from functools import partial

app = Flask(__name__)

# Configuration du logging plus détaillée
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Création d'un logger spécifique pour les captchas
captcha_logger = logging.getLogger('captcha_detection')
captcha_logger.setLevel(logging.DEBUG)

# Liste d'user agents pour rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
]

# Liste de proxies Decodo
PROXIES = [
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10001",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10002",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10003",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10004",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10005",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10006",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10007",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10008",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10009",
    "http://spjb20unmv:oDTdb+Rz49ff@gate.decodo.com:10010"
]

def get_proxy():
    """Sélectionne un proxy aléatoire de la liste"""
    if PROXIES:
        return random.choice(PROXIES)
    return None

def detect_captcha(driver):
    """Détecte la présence d'un captcha sur la page"""
    try:
        captcha_indicators = [
            "captcha",
            "recaptcha",
            "challenge",
            "verify you're human",
            "i'm not a robot",
            "err_no_supported_proxies",
            "err_proxy"
        ]
        
        page_source = driver.page_source.lower()
        for indicator in captcha_indicators:
            if indicator in page_source:
                captcha_logger.warning(f"DÉTECTION: '{indicator}' trouvé dans la page")
                return True
        
        title = driver.title.lower()
        if any(indicator in title for indicator in captcha_indicators):
            captcha_logger.warning(f"DÉTECTION dans le titre: {driver.title}")
            return True
            
        return False
    except Exception as e:
        captcha_logger.error(f"Erreur lors de la détection: {str(e)}")
        return False

def analyze_page(url, proxy=None):
    """Analyse une page web avec gestion des proxies (optimisée)"""
    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }
        
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=7)
        
        if resp.status_code == 403:
            logging.warning(f"Erreur 403 Forbidden pour {url}")
            
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Extraction optimisée
        page_title_tag = soup.find('title')
        page_title = page_title_tag.get_text(strip=True) if page_title_tag else "Aucun <title>"
        
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = meta_desc_tag["content"].strip() if meta_desc_tag and meta_desc_tag.get("content") else "Aucune meta description"
        
        h1 = soup.find('h1').get_text(strip=True) if soup.find('h1') else "Aucun H1"
        h2s = [tag.get_text(strip=True) for tag in soup.find_all('h2', limit=10)]
        
        word_count = len(soup.get_text().split())
        
        page_domain = urlparse(url).netloc
        internal_count = 0
        external_count = 0
        
        for link in soup.find_all('a', href=True, limit=100):
            link_domain = urlparse(link['href']).netloc
            if link_domain and link_domain == page_domain:
                internal_count += 1
            elif link_domain:
                external_count += 1
        
        media_counts = {
            "images": len(soup.find_all('img', limit=50)),
            "videos": len(soup.find_all('video', limit=10)),
            "audios": len(soup.find_all('audio', limit=10)),
            "embedded_videos": len(soup.find_all('iframe', src=lambda x: x and ('youtube' in x or 'vimeo' in x), limit=10))
        }
        
        structured_data_types = []
        for script_tag in soup.find_all("script", type="application/ld+json", limit=5):
            try:
                json_data = json.loads(script_tag.string)
                if isinstance(json_data, dict):
                    structured_data_types.append(json_data.get("@type", "Unknown"))
                elif isinstance(json_data, list):
                    for item in json_data[:3]:
                        if isinstance(item, dict):
                            structured_data_types.append(item.get("@type", "Unknown"))
            except:
                continue

        return {
            "url": url,
            "page_title": page_title,
            "meta_description": meta_description,
            "headers": {"H1": h1, "H2": h2s},
            "word_count": word_count,
            "internal_links": internal_count,
            "external_links": external_count,
            "media": media_counts,
            "structured_data": structured_data_types
        }

    except Exception as e:
        logging.error(f"Erreur d'analyse de {url}: {str(e)}")
        return {"error": str(e)}

def get_driver():
    """Configuration Selenium/Chromium optimisée"""
    logging.info("Création du driver Selenium avec undetected-chromedriver et proxy")
    
    try:
        options = uc.ChromeOptions()
        
        proxy = get_proxy()
        if proxy:
            proxy_parts = proxy.replace("http://", "").split("@")
            auth = proxy_parts[0]
            server = proxy_parts[1]
            username, password = auth.split(":")
            
            proxy_extension = f"""
            var config = {{
                mode: "fixed_servers",
                rules: {{
                    singleProxy: {{
                        scheme: "http",
                        host: "{server.split(':')[0]}",
                        port: parseInt("{server.split(':')[1]}")
                    }},
                    bypassList: ["localhost"]
                }}
            }};
            chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
            
            function callbackFn(details) {{
                return {{
                    authCredentials: {{
                        username: "{username}",
                        password: "{password}"
                    }}
                }};
            }}
            
            chrome.webRequest.onAuthRequired.addListener(
                callbackFn,
                {{urls: ["<all_urls>"]}},
                ['blocking']
            );
            """
            
            import zipfile
            import tempfile
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as proxy_zip:
                with zipfile.ZipFile(proxy_zip.name, 'w') as zp:
                    zp.writestr("manifest.json", json.dumps({
                        "version": "1.0.0",
                        "manifest_version": 2,
                        "name": "Chrome Proxy",
                        "permissions": [
                            "proxy",
                            "tabs",
                            "unlimitedStorage",
                            "storage",
                            "<all_urls>",
                            "webRequest",
                            "webRequestBlocking"
                        ],
                        "background": {
                            "scripts": ["background.js"]
                        },
                        "minimum_chrome_version": "22.0.0"
                    }))
                    zp.writestr("background.js", proxy_extension)
                
                options.add_extension(proxy_zip.name)
            
            logging.info(f"Utilisation du proxy: {proxy}")
        
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--start-maximized")
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-extensions-except=/tmp/proxy.zip')  # Only keep proxy extension
        options.add_argument('--disable-default-apps')
        options.add_argument('--no-first-run')
        options.add_argument('--no-service-autorun')
        
        driver = uc.Chrome(options=options, use_subprocess=True)
        driver.set_page_load_timeout(30)
        
        return driver
    except Exception as e:
        logging.error(f"Erreur lors de la création du driver: {str(e)}")
        logging.error(traceback.format_exc())
        raise

@app.route('/scrape', methods=['GET'])
def scrape_google_fr():
    """Endpoint GET pour scraper Google.fr optimisé"""
    query = request.args.get('query')
    if not query:
        logging.warning("Requête reçue sans paramètre 'query'")
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    driver = None
    try:
        logging.info(f"Lancement du scraping pour la requête : {query}")
        driver = get_driver()

        google_url = f"https://www.google.com/search?q={query}&gl=fr"
        logging.info(f"Navigation vers : {google_url}")
        
        driver.get(google_url)
        time.sleep(2)  # Attendre un peu pour le chargement

        # Détection de captcha
        if detect_captcha(driver):
            logging.error("PROBLÈME DÉTECTÉ - Captcha ou erreur de proxy")
            return jsonify({
                "error": "Problème de proxy ou captcha détecté",
                "code": 403,
                "details": "Vérifiez la configuration des proxies"
            }), 403

        # Attendre que la page soit chargée
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            logging.error(f"Timeout lors du chargement de la page: {str(e)}")
            raise

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Extraction optimisée
        paa_questions = [span.get_text(strip=True) for span in soup.select('span.CSkcDe') if span.get_text(strip=True)]
        logging.info(f"PAA trouvées: {len(paa_questions)}")

        associated_searches = [elem.get_text(strip=True) for elem in soup.select("div.y6Uyqe div.B2VR9.CJHX3e")]
        logging.info(f"Recherches associées trouvées: {len(associated_searches)}")

        # Différents sélecteurs pour trouver les résultats de recherche
        search_selectors = [
            "div.MjjYud",        # Sélecteur original
            "div.g",             # Sélecteur standard pour les résultats
            "div.tF2Cxc",        # Sélecteur alternatif
            "div[data-hveid]",   # Div avec attribut data-hveid
            "div.rc",            # Ancien sélecteur
            "div.N54PNb",        # Nouveau sélecteur potentiel
            "div.kvH3mc",        # Autre sélecteur potentiel
        ]
        
        search_results = []
        for selector in search_selectors:
            search_results = driver.find_elements(By.CSS_SELECTOR, selector)
            if search_results:
                logging.info(f"Résultats trouvés avec le sélecteur '{selector}': {len(search_results)}")
                break
        
        # Si aucun résultat n'est trouvé avec les sélecteurs standards
        if not search_results:
            logging.warning("Aucun résultat trouvé avec les sélecteurs standards, tentative de recherche alternative")
            # Recherche de tous les éléments avec un lien et un titre
            search_results = driver.find_elements(By.XPATH, "//div[.//h3 and .//a[@href]]")
            logging.info(f"Résultats trouvés avec XPath: {len(search_results)}")
        
        search_results = search_results[:10]  # Limiter à 10 résultats
        
        results = []
        proxy = get_proxy()

        for i, element in enumerate(search_results):
            try:
                logging.debug(f"Traitement du résultat {i+1}")
                
                # Essayer différentes méthodes pour obtenir le lien
                link = None
                try:
                    link = element.find_element(By.CSS_SELECTOR, "a[href]").get_attribute("href")
                except:
                    try:
                        link = element.find_element(By.XPATH, ".//a[@href]").get_attribute("href")
                    except:
                        logging.warning(f"Impossible de trouver le lien pour le résultat {i+1}")
                        continue
                
                # Filtrer les liens non pertinents
                if not link or "google.com" in link or "javascript:" in link:
                    continue
                
                # Obtenir le titre/snippet
                snippet = ""
                try:
                    snippet_elem = element.find_element(By.CSS_SELECTOR, "h3")
                    snippet = snippet_elem.text
                except:
                    try:
                        snippet_elem = element.find_element(By.XPATH, ".//h3")
                        snippet = snippet_elem.text
                    except:
                        snippet = "Sans titre"

                domain = urlparse(link).netloc
                logging.debug(f"URL: {link}, Domain: {domain}, Snippet: {snippet}")

                # Analyse de la page sans attente aléatoire
                page_info = analyze_page(link, proxy)

                result_info = {
                    "google_snippet": snippet,
                    "url": link,
                    "domain": domain,
                    "page_title": page_info.get("page_title", ""),
                    "meta_description": page_info.get("meta_description", ""),
                    "headers": page_info.get("headers", {}),
                    "word_count": page_info.get("word_count", 0),
                    "internal_links": page_info.get("internal_links", 0),
                    "external_links": page_info.get("external_links", 0),
                    "media": page_info.get("media", {}),
                    "structured_data": page_info.get("structured_data", [])
                }
                results.append(result_info)
            except Exception as e:
                logging.warning(f"Élément {i+1} ignoré : {str(e)}")
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
        logging.error(f"ERREUR: {str(e)}")
        logging.error(traceback.format_exc())
        
        if driver:
            try:
                screenshot_path = f"/tmp/error_screenshot_{int(time.time())}.png"
                driver.save_screenshot(screenshot_path)
                logging.info(f"Capture d'écran d'erreur sauvegardée : {screenshot_path}")
                
                logging.error(f"Titre de la page: {driver.title}")
                logging.error(f"URL actuelle: {driver.current_url}")
            except:
                pass
        
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