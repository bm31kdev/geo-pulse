# GeoPulse

**GeoPulse V1.1 DEBUG** est un studio Windows de simulation de trajet GPS pour iPhone, entièrement en français. Il associe une carte OpenStreetMap interactive, des itinéraires routiers OSRM et le service de développement DVT d’Apple via `pymobiledevice3`.

> Conçu pour les tests de développement et de géolocalisation sur un appareil que vous contrôlez.

## Fonctionnalités

- Carte OpenStreetMap interactive : clic pour poser des points, glisser pour déplacer, molette pour zoomer.
- Itinéraires routiers réels calculés avec OSRM.
- Vitesse réglable de 1 à 150 km/h, modes Marche, Vélo et Voiture, boucle, pause et reprise.
- Connexion USB, diagnostic d’appairage et préparation DVT pour l’iPhone.
- Restauration explicite de la localisation réelle à l’arrêt.
- Diagnostics transparents, y compris pour l’erreur `usbmuxd 183`.

## Démarrage

Prérequis : Windows et une connexion internet pour les tuiles OpenStreetMap et OSRM.

Double-cliquez sur `GeoPulse.lnk` à la racine du projet.

1. Cliquez une fois sur la carte pour le départ, puis une seconde fois pour la destination.
2. Cliquez sur **Calculer l’itinéraire**.
3. Réglez la vitesse, puis cliquez sur **Démarrer**.

## Utiliser un iPhone

L’iPhone doit être connecté par USB, déverrouillé, appairé avec Windows et avoir le Mode développeur activé.

1. Cliquez sur **Connecter et préparer l’iPhone**.
2. Attendez l’état « iPhone prêt pour la simulation GPS DVT ».
3. Choisissez un départ et une destination, puis calculez l’itinéraire.
4. Démarrez le trajet ou utilisez **Téléporter à la destination**.

GeoPulse utilise une session DVT persistante : la simulation n’a pas besoin d’un terminal interactif. Le bouton **Arrêter** appelle le service de restauration de la localisation réelle. Aucun fichier système iOS n’est modifié et l’appareil n’est jamais réinitialisé.

### Compatibilité iOS et dépannage

La simulation repose sur les interfaces de développement d’Apple et `pymobiledevice3`. iOS 17+ requiert un tunnel/RSD et une image de développement, que GeoPulse prépare via un tunnel userspace sans privilège administrateur. La compatibilité doit être vérifiée sur chaque version iOS ; les messages détaillés de l’outil ne sont jamais masqués.

En cas d’erreur `usbmuxd 183`, fermez Apple Devices/iTunes, débranchez puis rebranchez l’iPhone, déverrouillez-le et acceptez « Faire confiance ». Si nécessaire, redémarrez **Apple Mobile Device Service** dans les services Windows.

## Construire l’exécutable Windows

```powershell
python -m nuitka --assume-yes-for-downloads --standalone --windows-console-mode=disable --enable-plugin=pyside6 --nofollow-import-to=pymobiledevice3 --include-package=geo_pulse --include-data-dir=geo_pulse/web=geo_pulse/web --include-data-file=geo_pulse/dvt_worker.py=geo_pulse/dvt_worker.py --output-dir=geopulse_exe --output-filename=GeoPulse.exe main.py
```

L’exécutable est créé dans `geopulse_exe\main.dist\GeoPulse.exe`. Double-cliquez sur le raccourci Windows `GeoPulse.lnk` à la racine du projet pour l’ouvrir. La connexion USB utilise l’installation locale de `pymobiledevice3` présente sur ce PC.

## Tests

```powershell
python -m pytest -q
```

## Technologies

Python · PySide6 · OpenStreetMap · Leaflet · OSRM · pymobiledevice3 · Nuitka

## Références

- [DVT et simulation de localisation pymobiledevice3](https://doronz88.github.io/pymobiledevice3/api/dvt/)
- [Simuler une localisation avec les outils Apple](https://help.apple.com/xcode/mac/current/en.lproj/dev1b4074150.html)
