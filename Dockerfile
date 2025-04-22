FROM python:3.10-slim

# Mettre à jour et installer Chromium et Chromium-driver, ainsi que des utilitaires
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-dejavu \
    curl \
    gnupg \
    unzip \
    xvfb \
    xauth \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copier tout le contenu du projet dans le conteneur
COPY . .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Configurer les variables d'environnement pour Chromium
ENV DISPLAY=:99
ENV CHROMIUM_FLAGS="--disable-software-rasterizer --disable-dev-shm-usage"

# Exposer le port 8000 (Railway mappe ce port sur l'URL publique)
EXPOSE 8000

# Lancer l'application via Gunicorn avec Xvfb
CMD xvfb-run --server-args="-screen 0 1024x768x24" gunicorn -b 0.0.0.0:8000 --timeout 600 app:app