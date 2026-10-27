from __future__ import annotations
import os
# Doit être défini avant l'import de QtWebEngine. Le rendu logiciel est
# indispensable sur certains pilotes Windows/VM qui refusent GLES3.
os.environ['QT_OPENGL'] = 'software'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --disable-features=Vulkan'
import sys
from threading import Thread
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QUrl, Qt
from PySide6.QtWidgets import QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget
from geo_pulse.iphone_engine import MoteurIPhone, ErreurIPhone
from geo_pulse.route import calculer_itineraire, points_equidistants, ErreurItineraire
from geo_pulse.simulator import SimulateurTrajet
from geo_pulse.map_widget import CarteOSM


class Fenetre(QMainWindow):
    preparation_finie = Signal(object)
    def __init__(self):
        super().__init__(); self.setWindowTitle('GeoPulse'); self.resize(1380, 850)
        self.depart=None; self.destination=None; self.itineraire=None; self.iphone=MoteurIPhone(); self.simulation_iphone=False; self.iphone_pret=False; self.iphone_connecte=False
        root=QWidget(); self.setCentralWidget(root); layout=QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        panneau=QFrame(); panneau.setObjectName('panneau'); panneau.setFixedWidth(360); col=QVBoxLayout(panneau); col.setContentsMargins(24,26,24,24); col.setSpacing(12); layout.addWidget(panneau)
        titre=QLabel('Geo<span style="color:#38bdf8">Pulse</span>'); titre.setObjectName('titre'); col.addWidget(titre)
        sous=QLabel('Simulation GPS de développement'); sous.setObjectName('sous'); col.addWidget(sous)
        self.etat=QLabel('● Mode simulation locale'); self.etat.setObjectName('etat'); self.etat.setWordWrap(True); col.addWidget(self.etat)
        self.connecter=QPushButton('Connecter mon iPhone'); self.connecter.clicked.connect(self.connecter_iphone); col.addWidget(self.connecter)
        self.preparer=QPushButton('Préparer le GPS de l’iPhone'); self.preparer.clicked.connect(self.preparer_iphone); self.preparer.setEnabled(False); col.addWidget(self.preparer)
        self.local=QCheckBox('Mode simulation locale (sans iPhone)'); self.local.setChecked(True); self.local.toggled.connect(self.change_mode); col.addWidget(self.local)
        col.addWidget(QLabel('POINT DE DÉPART')); self.champ_depart=QLineEdit(); self.champ_depart.setPlaceholderText('Cliquez sur la carte ou saisissez : 48.8566, 2.3522'); self.champ_depart.editingFinished.connect(self.lire_champs); col.addWidget(self.champ_depart)
        col.addWidget(QLabel('DESTINATION')); self.champ_dest=QLineEdit(); self.champ_dest.setPlaceholderText('Cliquez sur la carte ou saisissez : 48.8584, 2.2945'); self.champ_dest.editingFinished.connect(self.lire_champs); col.addWidget(self.champ_dest)
        self.calculer=QPushButton('Calculer l’itinéraire'); self.calculer.clicked.connect(self.calculer_route); col.addWidget(self.calculer)
        col.addWidget(QLabel('MODE DE DÉPLACEMENT')); modes=QHBoxLayout(); self.groupe=QButtonGroup(self)
        for texte in ('Marche','Vélo','Voiture'):
            b=QRadioButton(texte); self.groupe.addButton(b); modes.addWidget(b)
            if texte=='Voiture': b.setChecked(True)
        col.addLayout(modes)
        self.vitesse_label=QLabel('Vitesse : 30 km/h'); col.addWidget(self.vitesse_label); self.vitesse=QSlider(); self.vitesse.setOrientation(Qt.Orientation.Horizontal); self.vitesse.setRange(1,150); self.vitesse.setValue(30); self.vitesse.valueChanged.connect(lambda v:self.vitesse_label.setText(f'Vitesse : {v} km/h')); col.addWidget(self.vitesse)
        self.boucle=QCheckBox('Trajet en boucle'); col.addWidget(self.boucle)
        infos=QFrame(); infos.setObjectName('infos'); ic=QVBoxLayout(infos); self.resume=QLabel('Distance : —\nDurée OSRM : —\nProgression : 0 %'); ic.addWidget(self.resume); col.addWidget(infos)
        actions=QHBoxLayout();
        for texte, action in [('Démarrer',self.demarrer),('Pause',self.pause),('Reprendre',self.reprendre),('Arrêter',self.arreter)]:
            b=QPushButton(texte); b.clicked.connect(action); actions.addWidget(b)
        col.addLayout(actions); col.addStretch()
        self.carte=CarteOSM(); layout.addWidget(self.carte,1); self.carte.clique.connect(self.point_carte)
        self.simulateur=SimulateurTrajet(); self.simulateur.position.connect(self.position); self.simulateur.erreur.connect(self.erreur); self.simulateur.termine.connect(lambda:self.message('Trajet terminé.'))
        self.preparation_finie.connect(self.preparation_terminee)
        self.setStyleSheet("""QMainWindow{background:#0f172a;color:#e2e8f0}#panneau{background:#111827}#titre{font-size:27px;font-weight:700}#sous{color:#94a3b8;margin-bottom:12px}QLabel{font-size:12px;color:#cbd5e1}#etat{background:#172554;color:#93c5fd;border-radius:7px;padding:10px}QLineEdit{background:#1f2937;border:1px solid #334155;border-radius:7px;padding:10px;color:#f8fafc}QPushButton{background:#0284c7;color:white;border:0;border-radius:7px;padding:10px;font-weight:600}QPushButton:hover{background:#0ea5e9}QRadioButton,QCheckBox{color:#e2e8f0}#infos{background:#1f2937;border-radius:7px;padding:4px}""")

    def point_carte(self, lat, lon):
        if self.depart is None or self.destination is not None:
            self.depart=(lat,lon); self.destination=None; self.champ_depart.setText(f'{lat:.6f}, {lon:.6f}'); self.champ_dest.clear(); self.carte.effacer()
            self.message('Départ choisi. Cliquez maintenant sur la destination.')
        else:
            self.destination=(lat,lon); self.champ_dest.setText(f'{lat:.6f}, {lon:.6f}'); self.carte.set_points(self.depart, self.destination)
            self.message('Destination choisie. Vous pouvez calculer l’itinéraire.')
    def lire_champs(self):
        """Accepte aussi une saisie manuelle, pratique si le rendu carte échoue."""
        try:
            def point(valeur):
                lat, lon = (float(x.strip().replace(',', '.')) for x in valeur.replace(';', ' ').split() if x.strip()) if ' ' in valeur and ',' not in valeur else (float(x.strip()) for x in valeur.replace(';', ',').split(','))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError
                return lat, lon
            if self.champ_depart.text().strip(): self.depart=point(self.champ_depart.text())
            if self.champ_dest.text().strip(): self.destination=point(self.champ_dest.text())
            if self.depart and self.destination: self.carte.set_points(self.depart, self.destination)
        except (ValueError, TypeError):
            self.erreur('Coordonnées invalides. Utilisez le format : latitude, longitude.')
    def connecter_iphone(self):
        e=self.iphone.verifier(); self.iphone_connecte=e.connecte; self.etat.setText(('● ' if e.connecte else '⚠ ') + e.message); self.preparer.setEnabled(e.connecte and not self.local.isChecked()); self.iphone_pret=False
        self.simulation_iphone=False
    def preparer_iphone(self):
        if self.local.isChecked(): return self.erreur('Décochez le mode local avant de préparer l’iPhone.')
        self.preparer.setEnabled(False); self.etat.setText('● Préparation du tunnel et de l’image de développement iPhone en cours…')
        Thread(target=self._preparer_iphone_worker, daemon=True).start()
    def _preparer_iphone_worker(self):
        try: resultat=self.iphone.preparer_simulation()
        except Exception as exc: resultat=type('Etat', (), {'connecte':False, 'message':str(exc)})()
        self.preparation_finie.emit(resultat)
    def preparation_terminee(self, resultat):
        self.iphone_pret=resultat.connecte; self.simulation_iphone=resultat.connecte and not self.local.isChecked()
        self.etat.setText(('● ' if resultat.connecte else '⚠ ') + resultat.message); self.preparer.setEnabled(not resultat.connecte)
    def change_mode(self, local):
        self.simulation_iphone=not local and self.iphone_pret
        self.preparer.setEnabled(not local and self.iphone_connecte and not self.iphone_pret)
        self.etat.setText('● Mode simulation locale — aucun iPhone n’est modifié.' if local else '⚠ Mode iPhone : cliquez sur « Connecter mon iPhone » pour vérifier l’appairage.')
    def calculer_route(self):
        if not self.depart or not self.destination: return self.erreur('Choisissez un départ puis une destination sur la carte.')
        try:
            self.itineraire=calculer_itineraire(self.depart,self.destination,self.groupe.checkedButton().text())
            pts=points_equidistants(self.itineraire.points); self.simulateur.charger(pts,self.vitesse.value(),self.boucle.isChecked())
            self.carte.dessiner_route(self.itineraire.points)
            self.resume.setText(f'Distance : {self.itineraire.distance_m/1000:.2f} km\nDurée OSRM : {self.itineraire.duree_s/60:.0f} min\nProgression : 0 %')
            self.message('Itinéraire calculé avec OSRM.')
        except ErreurItineraire as exc: self.erreur(str(exc))
    def demarrer(self):
        if not self.local.isChecked() and not self.iphone_pret:
            return self.erreur('iPhone non préparé : cliquez sur « Connecter mon iPhone », puis « Préparer le GPS de l’iPhone ».')
        if self.simulation_iphone: self.simulateur._emettre=self.iphone.envoyer
        else: self.simulateur._emettre=None
        self.simulateur.charger(points_equidistants(self.itineraire.points) if self.itineraire else [],self.vitesse.value(),self.boucle.isChecked()); self.simulateur.demarrer()
    def pause(self): self.simulateur.pause(); self.message('Simulation en pause.')
    def reprendre(self): self.simulateur.reprendre(); self.message('Simulation reprise.')
    def arreter(self):
        self.simulateur.arreter()
        # La restauration dépend de l'état réel du moteur, même si l'utilisateur
        # a basculé ensuite vers le mode local.
        if self.iphone.actif:
            try: self.iphone.restaurer()
            except ErreurIPhone as exc: return self.erreur(str(exc))
        self.message('Simulation arrêtée. Localisation réelle restaurée si un iPhone était actif.')
    def position(self, lat, lon, p): self.carte.afficher_position(lat, lon); self.resume.setText(self.resume.text().split('\nProgression')[0]+f'\nProgression : {p:.0f} %')
    def erreur(self, texte): QMessageBox.critical(self,'Erreur',texte); self.etat.setText('⚠ '+texte)
    def message(self, texte): self.statusBar().showMessage(texte,6000)
    def closeEvent(self,event): self.arreter(); event.accept()

if __name__=='__main__':
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app=QApplication(sys.argv); app.setApplicationName('GeoPulse'); w=Fenetre(); w.show(); sys.exit(app.exec())
