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
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Pour déboguer le HTML renvoyé par Google
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())

        # --- PAA
        paa_questions = [span.get_text(strip=True) for span in soup.select('span.CSkcDe') if span.get_text(strip=True)]

        # --- Recherches associées
        associated_searches = [elem.get_text(strip=True) for elem in soup.select("div.B2VR9.CJHX3e")]

        # --- Top 10
        search_results = soup.select("div.tF2Cxc")[:10]
        results = []

        for element in search_results:
            try:
                a_tag = element.select_one("a[href]")
                link = a_tag['href'] if a_tag else None
                snippet_elem = element.select_one("h3, span[role='heading']")
                google_snippet = snippet_elem.get_text(strip=True) if snippet_elem else "Sans titre"

                if not link:
                    continue

                domain = urlparse(link).netloc
                page_info = analyze_page(link)

                result_info = {
                    "google_snippet": google_snippet,
                    "url": link,
                    "domain": domain,
                    "page_title": page_info["page_title"],
                    "meta_description": page_info["meta_description"],
                    "headers": page_info["headers"],
                    "word_count": page_info["word_count"],
                    "internal_links": page_info["internal_links"],
                    "external_links": page_info["external_links"],
                    "media": page_info["media"],
                    "structured_data": page_info["structured_data"]
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
