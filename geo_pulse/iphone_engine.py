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
        if not self._localisation:
            raise ErreurIPhone("Service GPS iPhone non préparé. Cliquez sur « Préparer le GPS de l’iPhone ».")
        # Le service DVT reste ouvert pendant tout le trajet. L'ancien appel CLI
        # attendait ENTER après chaque set, d'où l'erreur « Aborted » sous subprocess.
        self._appeler(self._definir_position(latitude, longitude), timeout=15)
        self.actif = True

    def restaurer(self) -> None:
        if self._localisation:
            try:
                self._appeler(self._effacer_position(), timeout=15)
            except Exception as exc:
                raise ErreurIPhone(f"Impossible de restaurer la localisation réelle : {exc}") from exc
        self.actif = False

    def preparer_simulation(self) -> EtatIPhone:
        """Monte l'image de développement adaptée sans toucher aux données iOS.

        pymobiledevice3 choisit l'image adéquate (cryptex pour les versions
        iOS récentes). Le tunnel userspace ne demande pas de privilège admin.
        """
        etat = self.verifier()
        if not etat.connecte:
            return etat
        resultat = self._lancer(["mounter", "auto-mount", "--userspace"], timeout=180)
        if resultat.returncode:
            detail = (resultat.stderr or resultat.stdout).strip()
            return EtatIPhone(False, "Préparation DVT impossible : " + (detail or "erreur inconnue"))
        try:
            self._ouvrir_service_dvt()
        except Exception as exc:
            return EtatIPhone(False, f"Image de développement montée, mais service GPS DVT inaccessible : {exc}")
        return EtatIPhone(True, "iPhone prêt pour la simulation GPS DVT. Tunnel et service de localisation ouverts.")

    def _ouvrir_service_dvt(self) -> None:
        if self._localisation:
            return
        if not self._boucle:
            self._boucle = asyncio.new_event_loop()
            self._fil_boucle = Thread(target=self._executer_boucle, daemon=True, name="GeoPulse-DVT")
            self._fil_boucle.start()
        self._appeler(self._connexion_dvt(), timeout=45)

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
