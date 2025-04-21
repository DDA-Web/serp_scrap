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
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
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

        # Charger Google avec des paramètres spécifiques
        google_url = f"https://www.google.com/search?q={query}&gl=fr&hl=fr&pws=0"
        driver.get(google_url)
        
        # Attendre que la page se charge
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.TAG_NAME, "body").text != ""
        )
        
        # Pour assurer que tout le contenu est chargé
        time.sleep(3)
        
        # Scroll pour charger plus de contenu
        for i in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 4 * {});".format(i + 1))
            time.sleep(1)
        
        # Retourner en haut et défiler lentement pour charger les PAA
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(1)
        
        # --- PAA: approche multi-méthodes
        paa_questions = []
        
        # 1. Méthode JavaScript (la plus robuste face aux changements)
        try:
            js_paa_questions = driver.execute_script("""
                return Array.from(document.querySelectorAll('div[jsname][role="button"], div.related-question-pair, [data-q], div[data-ved][role="button"]'))
                    .filter(el => el.textContent.includes('?'))
                    .map(el => el.textContent.trim())
                    .filter(text => text.length > 10 && text.length < 200);
            """)
            
            if js_paa_questions and len(js_paa_questions) > 0:
                paa_questions = js_paa_questions
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction JavaScript des PAA: {str(e)}")
        
        # 2. Méthode XPath (plus spécifique)
        if not paa_questions:
            try:
                xpath_elements = driver.find_elements(By.XPATH, '//div[@jsname and @role="button" and contains(., "?")]')
                if not xpath_elements:
                    xpath_elements = driver.find_elements(By.XPATH, '//div[@data-ved and @role="button" and contains(., "?")]')
                if not xpath_elements:
                    xpath_elements = driver.find_elements(By.XPATH, '//div[contains(@class, "related-question") and contains(., "?")]')
                
                paa_questions = [elem.text.strip() for elem in xpath_elements 
                               if elem.text.strip() and elem.text.strip().endswith('?') 
                               and len(elem.text.strip()) > 10 and len(elem.text.strip()) < 200]
            except Exception as e:
                logging.warning(f"Erreur lors de l'extraction XPath des PAA: {str(e)}")
        
        # 3. Méthode BeautifulSoup pour analyse plus approfondie
        if not paa_questions:
            try:
                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                
                # Chercher des divs avec rôle de bouton
                button_divs = soup.find_all('div', attrs={'role': 'button'})
                for div in button_divs:
                    text = div.get_text(strip=True)
                    if text and text.endswith('?') and 10 < len(text) < 200:
                        paa_questions.append(text)
                
                # Chercher par motifs typiques des PAA
                if not paa_questions:
                    for element in soup.find_all(['div', 'span']):
                        # Chercher des attributs qui sont souvent présents dans les PAA
                        if (element.has_attr('jsname') or element.has_attr('data-ved') or 
                            ('related' in element.get('class', [])) or 
                            element.has_attr('data-q')):
                            
                            text = element.get_text(strip=True)
                            if text and text.endswith('?') and 10 < len(text) < 200:
                                paa_questions.append(text)
            except Exception as e:
                logging.warning(f"Erreur lors de l'extraction BeautifulSoup des PAA: {str(e)}")
        
        # --- Recherches associées
        associated_searches = []
        
        # 1. Utiliser JavaScript pour trouver les recherches associées
        try:
            js_searches = driver.execute_script("""
                // Chercher les sections qui contiennent "Recherches associées"
                let sections = Array.from(document.querySelectorAll('h3, h2, div')).filter(
                    el => el.textContent.toLowerCase().includes('recherches associées') || 
                          el.textContent.toLowerCase().includes('related searches')
                );
                
                if (sections.length > 0) {
                    // Trouver les liens dans le parent ou les frères suivants
                    let links = [];
                    sections.forEach(section => {
                        // Chercher dans le parent
                        let parent = section.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            let parentLinks = Array.from(parent.querySelectorAll('a')).filter(
                                a => a.textContent.trim().length > 0 && 
                                     a.textContent.trim().length < 100 && 
                                     !a.href.includes('#')
                            ).map(a => a.textContent.trim());
                            
                            links = links.concat(parentLinks);
                            parent = parent.parentElement;
                        }
                        
                        // Chercher dans les frères suivants
                        let nextSibling = section.nextElementSibling;
                        for (let i = 0; i < 5 && nextSibling; i++) {
                            let siblingLinks = Array.from(nextSibling.querySelectorAll('a')).filter(
                                a => a.textContent.trim().length > 0 && 
                                     a.textContent.trim().length < 100 && 
                                     !a.href.includes('#')
                            ).map(a => a.textContent.trim());
                            
                            links = links.concat(siblingLinks);
                            nextSibling = nextSibling.nextElementSibling;
                        }
                    });
                    
                    // Filtrer les doublons
                    return [...new Set(links)];
                }
                
                // Si rien n'est trouvé, essayer de trouver les liens en bas de page
                // qui sont généralement des recherches associées
                let allLinks = Array.from(document.querySelectorAll('a')).filter(
                    a => a.textContent.trim().length > 0 && 
                         a.textContent.trim().length < 100 && 
                         !a.href.includes('#') &&
                         !a.href.includes('google.com/search?')
                );
                
                // Prendre les derniers liens (généralement en bas de page)
                let bottomLinks = allLinks.slice(-15);
                return bottomLinks.map(a => a.textContent.trim());
            """)
            
            if js_searches and len(js_searches) > 0:
                associated_searches = js_searches
        except Exception as e:
            logging.warning(f"Erreur lors de l'extraction JavaScript des recherches associées: {str(e)}")
        
        # 2. Utiliser XPath comme méthode alternative
        if not associated_searches:
            try:
                # Chercher la section des recherches associées
                related_sections = driver.find_elements(By.XPATH, 
                    "//*[contains(text(), 'Recherches associées') or contains(text(), 'Related searches')]")
                
                if related_sections:
                    for section in related_sections:
                        # Trouver le conteneur parent
                        parent_container = driver.execute_script("""
                            var element = arguments[0];
                            var parent = element.parentElement;
                            for (let i = 0; i < 5 && parent; i++) {
                                if (parent.querySelectorAll('a').length > 2) return parent;
                                parent = parent.parentElement;
                            }
                            return null;
                        """, section)
                        
                        if parent_container:
                            # Trouver tous les liens dans ce conteneur
                            links = parent_container.find_elements(By.TAG_NAME, "a")
                            for link in links:
                                text = link.text.strip()
                                if text and len(text) > 3 and len(text) < 100:
                                    associated_searches.append(text)
            except Exception as e:
                logging.warning(f"Erreur lors de l'extraction XPath des recherches associées: {str(e)}")
        
        # --- Top 10
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Utiliser le sélecteur CSS standard
        search_results = driver.find_elements(By.CSS_SELECTOR, "div.MjjYud")
        
        # Si aucun résultat, essayer d'autres sélecteurs communs
        if not search_results or len(search_results) < 5:
            try:
                # Utiliser XPath pour trouver les résultats
                search_results = driver.find_elements(By.XPATH, "//div[.//h3 and .//a[@href]]")
            except:
                try:
                    # Essayer de trouver les liens principaux avec leurs parents
                    links = driver.find_elements(By.XPATH, "//a[.//h3]")
                    search_results = []
                    for link in links:
                        parent = driver.execute_script("""
                            var link = arguments[0];
                            return link.closest('div[data-ved], div[data-hveid]');
                        """, link)
                        if parent:
                            search_results.append(parent)
                except:
                    logging.warning("Impossible de trouver les résultats de recherche")
        
        results = []
        seen_urls = set()  # Pour éviter les doublons
        
        for element in (search_results[:10] if search_results else []):
            try:
                # Trouver le lien principal
                link = None
                
                try:
                    # Essayer de trouver un lien avec un h3
                    link_elements = element.find_elements(By.XPATH, ".//a[.//h3]")
                    if link_elements:
                        link = link_elements[0].get_attribute("href")
                except:
                    pass
                
                if not link:
                    try:
                        # Essayer de trouver un lien avec un span[role=heading]
                        link_elements = element.find_elements(By.XPATH, ".//a[.//span[@role='heading']]")
                        if link_elements:
                            link = link_elements[0].get_attribute("href")
                    except:
                        pass
                
                if not link:
                    try:
                        # Essayer de trouver le premier lien avec href
                        link_elements = element.find_elements(By.XPATH, ".//a[@href]")
                        if link_elements:
                            link = link_elements[0].get_attribute("href")
                    except:
                        continue
                
                # Vérifier si l'URL est valide et non un lien interne Google
                if not link or "google.com" in link or link in seen_urls:
                    continue
                
                seen_urls.add(link)
                
                # Trouver le snippet (titre)
                snippet = "Sans titre"
                
                try:
                    heading = element.find_element(By.TAG_NAME, "h3")
                    snippet = heading.text
                except:
                    try:
                        heading = element.find_element(By.XPATH, ".//span[@role='heading']")
                        snippet = heading.text
                    except:
                        pass
                
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

        # Filtrer les duplications dans les PAA
        if paa_questions:
            paa_questions = list(dict.fromkeys(paa_questions))

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