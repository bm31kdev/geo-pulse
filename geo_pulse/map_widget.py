"""Carte OSM native de secours pour les PC où QtWebEngine ne peut pas composer.

Leaflet reste fourni dans web/ pour les environnements WebEngine compatibles. Cette
vue Qt utilise les mêmes tuiles OpenStreetMap et conserve l'interaction complète.
"""
from __future__ import annotations

from math import atan, degrees, log, pi, radians, sinh, tan
from PySide6.QtCore import QPoint, QPointF, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply


class CarteOSM(QWidget):
    clique = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 400)
        self.setMouseTracking(True)
        self.zoom = 13
        self.centre = (48.8566, 2.3522)
        self._cache: dict[tuple[int, int, int], QPixmap | None] = {}
        self._en_cours: set[tuple[int, int, int]] = set()
        self._reseau = QNetworkAccessManager(self)
        self._route: list[tuple[float, float]] = []
        self._depart = self._destination = self._position = None
        self._drag_start: QPoint | None = None
        self._clic_depart: QPoint | None = None
        self._deplacement = False

    @staticmethod
    def _monde(lat: float, lon: float, zoom: int) -> QPointF:
        n = 256 * (2 ** zoom)
        x = (lon + 180) / 360 * n
        y = (1 - log(tan(radians(lat)) + 1 / __import__('math').cos(radians(lat))) / pi) / 2 * n
        return QPointF(x, y)

    @staticmethod
    def _coord(x: float, y: float, zoom: int) -> tuple[float, float]:
        n = 256 * (2 ** zoom)
        lon = x / n * 360 - 180
        lat = degrees(atan(sinh(pi * (1 - 2 * y / n))))
        return lat, lon

    def _top_left(self) -> QPointF:
        c = self._monde(*self.centre, self.zoom)
        return QPointF(c.x() - self.width() / 2, c.y() - self.height() / 2)

    def _tuile(self, x: int, y: int) -> QPixmap | None:
        limite = 2 ** self.zoom
        x %= limite
        if not 0 <= y < limite:
            return None
        cle = (self.zoom, x, y)
        if cle not in self._cache and cle not in self._en_cours:
            self._en_cours.add(cle)
            requete = QNetworkRequest(QUrl(f"https://tile.openstreetmap.org/{self.zoom}/{x}/{y}.png"))
            requete.setRawHeader(b"User-Agent", b"GeoPulse/1.0 (carte locale)")
            reponse = self._reseau.get(requete)
            reponse.finished.connect(lambda r=reponse, k=cle: self._tuile_recue(r, k))
        return self._cache.get(cle)

    def _tuile_recue(self, reponse: QNetworkReply, cle: tuple[int, int, int]) -> None:
        pix = QPixmap()
        self._cache[cle] = pix if reponse.error() == QNetworkReply.NetworkError.NoError and pix.loadFromData(reponse.readAll()) else None
        self._en_cours.discard(cle); reponse.deleteLater(); self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.fillRect(self.rect(), QColor('#1e293b'))
        haut = self._top_left(); premier_x, premier_y = int(haut.x() // 256), int(haut.y() // 256)
        for ty in range(premier_y, int((haut.y() + self.height()) // 256) + 1):
            for tx in range(premier_x, int((haut.x() + self.width()) // 256) + 1):
                px, py = round(tx * 256 - haut.x()), round(ty * 256 - haut.y())
                image = self._tuile(tx, ty)
                if image: p.drawPixmap(px, py, image)
                else:
                    p.fillRect(px, py, 256, 256, QColor('#334155'))
        if len(self._route) > 1:
            pen = QPen(QColor('#0284c7')); pen.setWidth(6); pen.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen)
            p.drawPolyline([self._ecran(a, b) for a, b in self._route])
        self._rond(p, self._depart, QColor('#22c55e'), 'D')
        self._rond(p, self._destination, QColor('#f97316'), 'A')
        self._rond(p, self._position, QColor('#ef4444'), '●')
        p.setPen(QColor('white')); p.drawText(12, self.height() - 12, '© OpenStreetMap  •  molette : zoom  •  clic gauche-glissé : déplacer  •  clic : point')

    def _ecran(self, lat, lon):
        m, h = self._monde(lat, lon, self.zoom), self._top_left()
        return QPoint(round(m.x() - h.x()), round(m.y() - h.y()))

    def _rond(self, p, coord, couleur, texte):
        if not coord: return
        q = self._ecran(*coord); p.setBrush(couleur); p.setPen(QPen(QColor('white'), 2)); p.drawEllipse(q, 10, 10)
        p.setPen(QColor('white')); p.drawText(q.x()-4, q.y()+5, texte)

    def set_points(self, depart, destination): self._depart, self._destination = depart, destination; self.update()
    def dessiner_route(self, points): self._route = points; self.update()
    def afficher_position(self, lat, lon): self._position = (lat, lon); self.centre = self._position; self.update()
    def effacer(self): self._route=[]; self._depart=self._destination=self._position=None; self.update()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag_start = event.position().toPoint()
            self._clic_depart = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
            self._deplacement = False

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.position().toPoint() - self._drag_start; m = self._monde(*self.centre, self.zoom)
            if delta.manhattanLength() >= 3:
                self._deplacement = True
                self.centre = self._coord(m.x()-delta.x(), m.y()-delta.y(), self.zoom)
                self._drag_start = event.position().toPoint(); self.update()

    def mouseReleaseEvent(self, event):
        # Un clic court choisit un point; un glissé ne le fait jamais.
        if event.button() == Qt.MouseButton.LeftButton and self._clic_depart is not None and not self._deplacement:
            h = self._top_left(); q = event.position()
            self.clique.emit(*self._coord(h.x()+q.x(), h.y()+q.y(), self.zoom))
        self._drag_start = self._clic_depart = None; self._deplacement = False

    def wheelEvent(self, event):
        variation = 1 if event.angleDelta().y() > 0 else -1
        nouveau_zoom = max(2, min(19, self.zoom + variation))
        if nouveau_zoom == self.zoom: return
        # Garde le point sous le curseur immobile pendant le zoom.
        h = self._top_left(); q = event.position(); point = self._coord(h.x()+q.x(), h.y()+q.y(), self.zoom)
        self.zoom = nouveau_zoom
        monde = self._monde(*point, self.zoom)
        self.centre = self._coord(monde.x()-q.x()+self.width()/2, monde.y()-q.y()+self.height()/2, self.zoom)
        self.update()
