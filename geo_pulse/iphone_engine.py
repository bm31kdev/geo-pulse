"""Moteur isolé de détection et de simulation iPhone.

Il utilise les commandes publiques pymobiledevice3, afin de rester compatible avec
les évolutions de cette bibliothèque sans copier ses API internes asynchrones.
"""
from __future__ import annotations
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
from dataclasses import dataclass


class ErreurIPhone(RuntimeError):
    pass


@dataclass(frozen=True)
class EtatIPhone:
    connecte: bool
    message: str
    nom: str = "—"
    modele: str = "—"
    ios: str = "—"
    udid: str = "—"
    numero: str = "—"
    mode_developpeur: bool = False


class MoteurIPhone:
    """Pont vers pymobiledevice3. Aucun fichier système iOS n'est modifié."""
    def __init__(self) -> None:
        self.commande = shutil.which("pymobiledevice3")
        # pip installe souvent Scripts hors du PATH sur Windows Store Python.
        # L'appel par module reste alors parfaitement fonctionnel.
        self.prefixe = [self.commande] if self.commande else [sys.executable, "-m", "pymobiledevice3"]
        self.actif = False
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._fil_boucle: Thread | None = None
        self._tunnel = self._dvt = self._localisation = None
        self._worker_dvt: subprocess.Popen[str] | None = None

    @property
    def _est_compile(self) -> bool:
        """Nuitka définit __compiled__, PyInstaller utilise sys.frozen."""
        return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))

    def _lancer(self, arguments: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run([*self.prefixe, *arguments], text=True, capture_output=True, timeout=timeout, check=False,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise ErreurIPhone(f"Impossible de démarrer pymobiledevice3 : {exc}") from exc

    def verifier(self) -> EtatIPhone:
        resultat = self._lancer(["usbmux", "list"], timeout=12)
        texte = (resultat.stdout + "\n" + resultat.stderr).strip()
        if resultat.returncode == 0 and texte:
            appairage = self._lancer(["lockdown", "info"], timeout=15)
            detail = (appairage.stdout + "\n" + appairage.stderr).strip()
            if appairage.returncode == 0:
                try:
                    infos = json.loads(appairage.stdout)
                    version = str(infos.get("ProductVersion", "inconnue"))
                    etat = EtatIPhone(
                        True, "iPhone USB détecté et appairage vérifié.",
                        str(infos.get("DeviceName", "iPhone")), str(infos.get("ProductType", "iPhone")), version,
                        str(infos.get("UniqueDeviceID", "—")), str(infos.get("PhoneNumber", "—")),
                    )
                    majeur = int(version.split(".")[0])
                    if majeur < 17:
                        return EtatIPhone(False, f"iOS {version} est trop ancien : iOS 17 ou supérieur est requis.", nom=etat.nom, modele=etat.modele, ios=etat.ios, udid=etat.udid, numero=etat.numero)
                    mode = self._lancer(["amfi", "developer-mode-status"], timeout=12)
                    actif = mode.returncode == 0 and "true" in mode.stdout.lower()
                    if not actif:
                        return EtatIPhone(False, "Mode développeur désactivé : activez-le dans Réglages > Confidentialité et sécurité.", nom=etat.nom, modele=etat.modele, ios=etat.ios, udid=etat.udid, numero=etat.numero)
                    return EtatIPhone(**etat.__dict__ | {"mode_developpeur": True})
                except (ValueError, json.JSONDecodeError):
                    return EtatIPhone(True, "iPhone USB détecté et appairage vérifié.")
            if "183" in detail:
                return EtatIPhone(False, "Erreur usbmuxd 183 : fermez iTunes/Apple Devices, débranchez/rebranchez l'iPhone, puis réessayez.")
            return EtatIPhone(False, "iPhone détecté, mais appairage/verrouillage refusé : " + (detail or "détail indisponible"))
        if "183" in texte:
            return EtatIPhone(False, "Erreur usbmuxd 183 : fermez iTunes/Apple Devices, débranchez/rebranchez l'iPhone, puis réessayez.")
        return EtatIPhone(False, f"Aucun iPhone utilisable ou appairage refusé. Détail : {texte or 'aucun périphérique détecté'}")

    def envoyer(self, latitude: float, longitude: float) -> None:
        if self._est_compile:
            if not self._worker_dvt:
                raise ErreurIPhone("Service GPS iPhone non préparé. Cliquez sur « Préparer le GPS de l’iPhone ».")
            commande = {"action": "set", "latitude": latitude, "longitude": longitude}
            try:
                self._commande_worker(commande)
            except ErreurIPhone:
                # Le tunnel iOS peut expirer après une veille ou un bref
                # débranchement USB. Recréez-le une fois avant d'abandonner.
                self._worker_dvt.terminate()
                self._worker_dvt = None
                self._ouvrir_worker_dvt()
                self._commande_worker(commande)
            self.actif = True
            return
        if not self._localisation:
            raise ErreurIPhone("Service GPS iPhone non préparé. Cliquez sur « Préparer le GPS de l’iPhone ».")
        # Le service DVT reste ouvert pendant tout le trajet. L'ancien appel CLI
        # attendait ENTER après chaque set, d'où l'erreur « Aborted » sous subprocess.
        self._appeler(self._definir_position(latitude, longitude), timeout=15)
        self.actif = True

    def restaurer(self) -> None:
        if self._est_compile and self._worker_dvt:
            try:
                self._commande_worker({"action": "clear"})
                self._commande_worker({"action": "quitter"}, timeout=5)
            except Exception as exc:
                raise ErreurIPhone(f"Impossible de restaurer la localisation réelle : {exc}") from exc
            finally:
                self._worker_dvt.terminate()
                self._worker_dvt = None
            self.actif = False
            return
        if self._localisation:
            try:
                self._appeler(self._effacer_position(), timeout=15)
            except Exception as exc:
                raise ErreurIPhone(f"Impossible de restaurer la localisation réelle : {exc}") from exc
        self.actif = False

    def preparer_simulation(self, etat: EtatIPhone | None = None) -> EtatIPhone:
        """Monte l'image de développement adaptée sans toucher aux données iOS.

        pymobiledevice3 choisit l'image adéquate (cryptex pour les versions
        iOS récentes). Le tunnel userspace ne demande pas de privilège admin.
        """
        etat = etat or self.verifier()
        if not etat.connecte:
            return etat
        resultat = self._lancer(["mounter", "auto-mount", "--userspace"], timeout=180)
        if resultat.returncode:
            detail = (resultat.stderr or resultat.stdout).strip()
            return EtatIPhone(False, "Préparation DVT impossible : " + (detail or "erreur inconnue"),
                              etat.nom, etat.modele, etat.ios, etat.udid, etat.numero, etat.mode_developpeur)
        try:
            self._ouvrir_service_dvt()
        except Exception as exc:
            return EtatIPhone(False, f"Image de développement montée, mais service GPS DVT inaccessible : {exc}",
                              etat.nom, etat.modele, etat.ios, etat.udid, etat.numero, etat.mode_developpeur)
        return EtatIPhone(True, "iPhone prêt pour la simulation GPS DVT. Tunnel et service de localisation ouverts.",
                          etat.nom, etat.modele, etat.ios, etat.udid, etat.numero, etat.mode_developpeur)

    def _ouvrir_service_dvt(self) -> None:
        if self._localisation:
            return
        if self._est_compile:
            self._ouvrir_worker_dvt()
            return
        if not self._boucle:
            self._boucle = asyncio.new_event_loop()
            self._fil_boucle = Thread(target=self._executer_boucle, daemon=True, name="GeoPulse-DVT")
            self._fil_boucle.start()
        self._appeler(self._connexion_dvt(), timeout=45)

    def _ouvrir_worker_dvt(self) -> None:
        """DVT reste dans Python normal ; l'EXE Nuitka reste ainsi léger.

        pymobiledevice3 est déjà installé avec GeoPulse sur ce PC. Ce processus
        local ne fait qu'héberger la session DVT persistante, il n'envoie aucune
        donnée hors de l'ordinateur.
        """
        if self._worker_dvt and self._worker_dvt.poll() is None:
            return
        if not self.commande:
            raise ErreurIPhone("pymobiledevice3 est introuvable. Réinstallez les dépendances avec requirements.txt.")
        python = Path(self.commande).parent.parent / "python.exe"
        script = Path(sys.argv[0]).resolve().parent / "geo_pulse" / "dvt_worker.py"
        if not python.exists() or not script.exists():
            raise ErreurIPhone("Pont GPS DVT introuvable dans l’installation GeoPulse.")
        derniere_erreur: Exception | None = None
        # Un tunnel précédent peut rester bloqué après un débranchement USB.
        # Une seconde session propre résout ce cas sans masquer l'erreur finale.
        for tentative in range(2):
            self._worker_dvt = subprocess.Popen(
                [str(python), str(script)], text=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                self._commande_worker({"action": "ouvrir"}, timeout=25)
                return
            except ErreurIPhone as exc:
                derniere_erreur = exc
                self._worker_dvt.terminate()
                self._worker_dvt = None
                if tentative == 0:
                    time.sleep(1)
        raise ErreurIPhone(f"Service GPS DVT inaccessible après une nouvelle tentative : {derniere_erreur}")

    @property
    def service_actif(self) -> bool:
        return bool(self._worker_dvt or self._localisation)

    def _commande_worker(self, commande: dict[str, object], timeout: int = 15) -> dict[str, object]:
        if not self._worker_dvt or not self._worker_dvt.stdin or not self._worker_dvt.stdout:
            raise ErreurIPhone("Pont GPS DVT non démarré.")
        self._worker_dvt.stdin.write(json.dumps(commande) + "\n")
        self._worker_dvt.stdin.flush()
        reponses: Queue[str] = Queue(maxsize=1)
        Thread(target=lambda: reponses.put(self._worker_dvt.stdout.readline()), daemon=True).start()
        try:
            ligne = reponses.get(timeout=timeout)
            resultat = json.loads(ligne)
        except (Empty, json.JSONDecodeError) as exc:
            raise ErreurIPhone("Le pont GPS DVT ne répond pas. Reconnectez l’iPhone puis réessayez.") from exc
        if not resultat.get("ok"):
            raise ErreurIPhone(str(resultat.get("erreur", "Erreur DVT inconnue.")))
        return resultat

    def _executer_boucle(self) -> None:
        assert self._boucle is not None
        asyncio.set_event_loop(self._boucle)
        self._boucle.run_forever()

    def _appeler(self, coroutine, timeout: int):
        if not self._boucle:
            raise ErreurIPhone("Boucle DVT non initialisée.")
        return asyncio.run_coroutine_threadsafe(coroutine, self._boucle).result(timeout=timeout)

    async def _connexion_dvt(self) -> None:
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        self._tunnel = UserspaceRsdTunnel()
        rsd = await self._tunnel.aopen()
        self._dvt = DvtProvider(rsd)
        await self._dvt.__aenter__()
        self._localisation = LocationSimulation(self._dvt)
        await self._localisation.__aenter__()

    async def _definir_position(self, latitude: float, longitude: float) -> None:
        await self._localisation.set(latitude, longitude)

    async def _effacer_position(self) -> None:
        await self._localisation.clear()
