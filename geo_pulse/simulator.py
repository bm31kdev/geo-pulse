"""Lecteur de trajet à vitesse contrôlée, utilisable localement ou avec un émetteur iPhone."""
from __future__ import annotations
from typing import Callable
from PySide6.QtCore import QObject, QTimer, Signal
from .route import distance_m


class SimulateurTrajet(QObject):
    position = Signal(float, float, float)  # lat, lon, progression 0..100
    termine = Signal()
    erreur = Signal(str)

    def __init__(self, emettre: Callable[[float, float], None] | None = None) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avance)
        self._points: list[tuple[float, float]] = []
        self._index = 0
        self._vitesse = 30.0
        self._emettre = emettre
        self._boucle = False

    def charger(self, points: list[tuple[float, float]], vitesse_kmh: float, boucle: bool) -> None:
        self.arreter()
        self._points, self._index = points, 0
        self._vitesse, self._boucle = max(1, vitesse_kmh), boucle

    def demarrer(self) -> None:
        if len(self._points) < 2:
            self.erreur.emit("Calculez d'abord un itinéraire valide.")
            return
        self._timer.start(500)
        self._avance()

    def pause(self) -> None: self._timer.stop()
    def reprendre(self) -> None:
        if self._points and self._index < len(self._points): self._timer.start(500)
    def arreter(self) -> None:
        self._timer.stop(); self._index = 0

    def _avance(self) -> None:
        try:
            lat, lon = self._points[self._index]
            if self._emettre: self._emettre(lat, lon)
            self.position.emit(lat, lon, 100 * self._index / max(1, len(self._points) - 1))
            # Le pas est de ~8 m: consommation de plusieurs points selon la vitesse.
            pas = max(1, round((self._vitesse / 3.6 * 0.5) / 8))
            self._index += pas
            if self._index >= len(self._points):
                if self._boucle: self._index = 0
                else: self._timer.stop(); self.termine.emit()
        except Exception as exc:
            self._timer.stop(); self.erreur.emit(str(exc))
