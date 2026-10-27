"""Pont local persistant pour la simulation DVT, utilisé par l'EXE Nuitka."""

from __future__ import annotations

import asyncio
import json
import sys


async def principal() -> None:
    tunnel = dvt = localisation = None

    async def ouvrir() -> None:
        nonlocal tunnel, dvt, localisation
        if localisation:
            return
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

        tunnel = UserspaceRsdTunnel()
        rsd = await tunnel.aopen()
        dvt = DvtProvider(rsd)
        await dvt.__aenter__()
        localisation = LocationSimulation(dvt)
        await localisation.__aenter__()

    for ligne in sys.stdin:
        try:
            commande = json.loads(ligne)
            action = commande.get("action")
            if action == "ouvrir":
                await ouvrir()
            elif action == "set":
                await ouvrir()
                await localisation.set(float(commande["latitude"]), float(commande["longitude"]))
            elif action == "clear":
                if localisation:
                    await localisation.clear()
            elif action == "quitter":
                print(json.dumps({"ok": True}), flush=True)
                return
            else:
                raise ValueError("Commande DVT inconnue.")
            print(json.dumps({"ok": True}), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "erreur": str(exc)}), flush=True)


if __name__ == "__main__":
    asyncio.run(principal())
