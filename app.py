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
    """Analyse une page web avec gestion des proxies"""
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
    """Configuration Selenium/Chromium avec support proxy amélioré"""
    logging.info("Création du driver Selenium avec undetected-chromedriver et proxy")
    
    try:
        options = uc.ChromeOptions()
        
        # Configuration du proxy
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
        
        # Ajout d'un profil utilisateur pour persister les cookies
        user_data_dir = os.path.join(os.getcwd(), 'chrome_profile')
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
        options.add_argument(f'--user-data-dir={user_data_dir}')
        
        driver = uc.Chrome(options=options, use_subprocess=True)
        driver.set_page_load_timeout(60)
        
        # Ajout de cookies pour paraître plus légitime
        driver.get("https://www.google.com")
        time.sleep(random.uniform(2, 4))
        
        logging.info("Driver créé avec succès")
        return driver
    except Exception as e:
        logging.error(f"Erreur lors de la création du driver: {str(e)}")
        logging.error(traceback.format_exc())
        raise

@app.route('/scrape', methods=['GET'])
def scrape_google_fr():
    """Endpoint GET pour scraper Google.fr avec gestion des proxies"""
    query = request.args.get('query')
    if not query:
        logging.warning("Requête reçue sans paramètre 'query'")
        return jsonify({"error": "Paramètre 'query' requis"}), 400

    max_retries = 3
    for attempt in range(max_retries):
        driver = None
        try:
            logging.info(f"Lancement du scraping pour la requête : {query} (tentative {attempt + 1}/{max_retries})")
            driver = get_driver()

            # Navigation vers Google avec délai aléatoire
            google_url = f"https://www.google.com/search?q={query}&gl=fr"
            logging.info(f"Navigation vers : {google_url}")
            
            # Simulation de comportement humain
            time.sleep(random.uniform(2, 4))
            
            # Accepter les cookies si présents
            try:
                driver.get("https://www.google.com")
                time.sleep(2)
                cookie_button = driver.find_element(By.XPATH, "//button[contains(., 'Accept all') or contains(., 'Tout accepter')]")
                cookie_button.click()
                time.sleep(1)
            except:
                pass
            
            driver.get(google_url)
            time.sleep(random.uniform(3, 5))

            # Log de l'URL actuelle après navigation
            logging.info(f"URL actuelle : {driver.current_url}")
            
            # Détection de captcha ou d'erreurs de proxy
            if detect_captcha(driver):
                logging.error("PROBLÈME DÉTECTÉ - Changement de proxy et nouvelle tentative")
                
                # Capture d'écran pour debug
                try:
                    screenshot_path = f"/tmp/error_screenshot_{int(time.time())}.png"
                    driver.save_screenshot(screenshot_path)
                    logging.info(f"Capture d'écran sauvegardée : {screenshot_path}")
                except Exception as e:
                    logging.error(f"Impossible de sauvegarder la capture d'écran: {str(e)}")
                
                if attempt < max_retries - 1:
                    continue  # Réessayer avec un nouveau proxy
                else:
                    return jsonify({
                        "error": "Problème de proxy ou captcha détecté après plusieurs tentatives",
                        "code": 403,
                        "details": "Vérifiez la configuration des proxies"
                    }), 403

            # Attente du chargement de la page
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: d.find_element(By.TAG_NAME, "body").text != ""
                )
                logging.info("Page chargée avec succès")
            except Exception as e:
                logging.error(f"Timeout lors du chargement de la page: {str(e)}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise

            # Simulation de comportement humain
            time.sleep(random.uniform(2, 4))
            
            # Scroll progressif
            for i in range(3):
                driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight*{i/3});")
                time.sleep(random.uniform(0.5, 1))
            
            # Attendre un peu après le scroll
            time.sleep(random.uniform(1, 2))

            html = driver.page_source
            logging.debug(f"HTML récupéré, longueur: {len(html)} caractères")
            
            soup = BeautifulSoup(html, 'html.parser')

            # Extraction des données
            paa_questions = [span.get_text(strip=True) for span in soup.select('span.CSkcDe') if span.get_text(strip=True)]
            logging.info(f"PAA trouvées: {len(paa_questions)}")

            associated_searches = [elem.get_text(strip=True) for elem in soup.select("div.y6Uyqe div.B2VR9.CJHX3e")]
            logging.info(f"Recherches associées trouvées: {len(associated_searches)}")

            # Différents sélecteurs pour les résultats de recherche
            search_selectors = [
                "div.g",             # Sélecteur standard pour les résultats
                "div.tF2Cxc",        # Sélecteur alternatif
                "div.hlcw0c",        # Autre sélecteur potentiel
                "div[class*='g ']",  # Divs avec classe contenant 'g'
                "div[data-hveid]",   # Div avec attribut data-hveid
                "div.MjjYud"         # Sélecteur original
            ]
            
            search_results = []
            for selector in search_selectors:
                search_results = driver.find_elements(By.CSS_SELECTOR, selector)
                if search_results:
                    logging.info(f"Résultats trouvés avec le sélecteur '{selector}': {len(search_results)}")
                    break
            
            # Si aucun résultat n'est trouvé, essayer une approche alternative
            if not search_results:
                logging.warning("Aucun résultat trouvé avec les sélecteurs standards, recherche alternative")
                # Trouver tous les éléments qui ont un h3 et un lien
                search_results = driver.find_elements(By.XPATH, "//div[descendant::h3 and descendant::a[@href and not(contains(@href, 'google.com')) and not(contains(@href, 'javascript:'))]]")
                logging.info(f"Résultats trouvés avec XPath alternatif: {len(search_results)}")
            
            search_results = search_results[:10]  # Limiter aux 10 premiers résultats
            
            results = []

            for i, element in enumerate(search_results):
                try:
                    logging.debug(f"Traitement du résultat {i+1}")
                    
                    # Essayer différentes approches pour obtenir le lien
                    link = None
                    try:
                        # Rechercher un lien direct dans l'élément
                        link_elem = element.find_element(By.CSS_SELECTOR, "a[href]")
                        link = link_elem.get_attribute("href")
                    except:
                        try:
                            # Rechercher dans les descendants
                            link_elem = element.find_element(By.XPATH, ".//a[@href]")
                            link = link_elem.get_attribute("href")
                        except:
                            logging.warning(f"Impossible de trouver le lien pour le résultat {i+1}")
                            continue
                    
                    # Filtrer les liens non pertinents
                    if not link or any(x in link for x in ["google.com", "javascript:", "accounts.google.com", "support.google.com"]):
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

                    # Analyse rapide de la page
                    page_info = analyze_page(link, get_proxy())

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
            logging.error(f"ERREUR (tentative {attempt + 1}/{max_retries}): {str(e)}")
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
            
            if attempt < max_retries - 1:
                continue
            else:
                return jsonify({
                    "error": "Service temporairement indisponible après plusieurs tentatives",
                    "code": 503,
                    "details": str(e)
                }), 503

        finally:
            if driver:
                driver.quit()
                logging.info("Fermeture du navigateur.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)