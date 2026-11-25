#!/usr/bin/env python3
"""Capture une vraie capture d'écran (PNG) de l'IHM Miami Vice, authentifiée,
via Chrome DevTools Protocol (CDP) en websocket - utilisé pour le "mode
d'emploi illustré" (plan-mark4.md action 3a/3b/3c).

Pourquoi CDP et pas un simple `--screenshot` one-shot : l'app est une SPA
sans routing par URL (frontend/src/App.tsx, state React `page` en mémoire)
et son token d'authentification vit en localStorage sur l'origine
http://localhost:3000 (clé 'miami-vice-auth-token',
frontend/src/api.ts:AUTH_TOKEN_STORAGE_KEY). Il faut donc : naviguer une
première fois sur l'origine (pour que `localStorage.setItem` s'applique à
la bonne origine), poser le token, recharger pour démarrer authentifié,
puis simuler les clics de navigation (onglet Configuration/Navigation,
sélection de la meta-classe/classe dans la Sidebar) avant de capturer.

Prérequis :
  - Chrome headless lancé séparément avec le CDP exposé en HTTP, ex. :
      google-chrome --headless=new --remote-debugging-port=9333 \\
        --remote-allow-origins=* --no-sandbox \\
        --user-data-dir=<profil dédié> --window-size=1280,900 about:blank
    (--remote-allow-origins=* requis par les versions récentes de Chrome,
    sinon le handshake websocket est rejeté en 403.)
  - Un token Keycloak valide (password grant testuser/testuser123, cf.
    frontend/src/api.ts apiLogin) dans un fichier texte.
  - pip : websocket-client, requests.

Usage :
  python3 tools/screenshot_demo.py \\
    --token-file /chemin/vers/token.txt \\
    --page configuration --meta-class demo_vin \\
    --out doc/demo-vin/configuration.png

  python3 tools/screenshot_demo.py \\
    --token-file /chemin/vers/token.txt \\
    --page navigation --meta-class demo_vin --class bouteille \\
    --out doc/demo-vin/navigation.png
"""
import argparse
import base64
import json
import time

import requests
import websocket  # websocket-client


def new_tab_ws(cdp_host: str):
    r = requests.put(f"{cdp_host}/json/new?about:blank")
    r.raise_for_status()
    info = r.json()
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=30)
    return ws, info["id"]


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 0

    def send(self, method, params=None):
        self.msg_id += 1
        self.ws.send(json.dumps({"id": self.msg_id, "method": method, "params": params or {}}))
        return self.msg_id

    def recv_until(self, wanted_id=None, wanted_event=None, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(0.5, deadline - time.time()))
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                break
            msg = json.loads(raw)
            if wanted_id is not None and msg.get("id") == wanted_id:
                return msg
            if wanted_event is not None and msg.get("method") == wanted_event:
                return msg
        raise TimeoutError(f"CDP timeout waiting id={wanted_id} event={wanted_event}")

    def call(self, method, params=None, timeout=20):
        mid = self.send(method, params)
        msg = self.recv_until(wanted_id=mid, timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method} failed: {msg['error']}")
        return msg.get("result")

    def wait_event(self, event, timeout=20):
        return self.recv_until(wanted_event=event, timeout=timeout)


def evaluate(cdp, expr):
    res = cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    result = res.get("result", {})
    return result.get("value")


def screenshot(cdp, path):
    res = cdp.call("Page.captureScreenshot", {"format": "png"})
    data = base64.b64decode(res["data"])
    with open(path, "wb") as f:
        f.write(data)
    print(f"Screenshot saved: {path} ({len(data)} bytes)")


def goto(cdp, url):
    cdp.call("Page.navigate", {"url": url})
    cdp.wait_event("Page.loadEventFired", timeout=30)
    time.sleep(1.0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cdp-host", default="http://localhost:9333")
    p.add_argument("--frontend-url", default="http://localhost:3000")
    p.add_argument("--token-file", required=True, help="Fichier texte contenant un access_token Keycloak brut")
    p.add_argument("--page", choices=["configuration", "navigation", "diagramme"], required=True)
    p.add_argument("--meta-class", required=True, help="meta_class à sélectionner dans la Sidebar (badge-meta)")
    p.add_argument("--class", dest="cls", default=None,
                   help="Nom de classe à sélectionner en plus (page navigation uniquement, narrow la liste)")
    p.add_argument("--out", required=True, help="Chemin du PNG de sortie")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=900)
    args = p.parse_args()

    with open(args.token_file) as f:
        token = f.read().strip()

    ws, tab_id = new_tab_ws(args.cdp_host)
    cdp = CDP(ws)
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Page.setDeviceMetricsOverride", {
        "width": args.width, "height": args.height, "deviceScaleFactor": 1, "mobile": False,
    })

    # 1er chargement sur l'origine cible (nécessaire avant tout setItem).
    goto(cdp, args.frontend_url)
    print("set token:", evaluate(cdp, f"localStorage.setItem('miami-vice-auth-token', {json.dumps(token)}); 'ok'"))

    # Reload pour démarrer authentifié (Navbar lit getAuthToken() au montage).
    goto(cdp, args.frontend_url)
    time.sleep(1.5)
    print("token present after reload:", evaluate(cdp, "!!localStorage.getItem('miami-vice-auth-token')"))

    label = {"configuration": "Configuration", "navigation": "Navigation", "diagramme": "Diagramme"}[args.page]
    print("click nav:", evaluate(cdp, f"""
    (function() {{
      const b = [...document.querySelectorAll('nav.navbar button')].find(x => x.textContent.trim() === '{label}');
      if (!b) return 'NOT_FOUND';
      b.click();
      return 'clicked:' + b.textContent;
    }})()
    """))
    time.sleep(1.0)

    print("click meta:", evaluate(cdp, f"""
    (function() {{
      const badges = [...document.querySelectorAll('.badge-meta')];
      const b = badges.find(x => x.textContent.trim() === {json.dumps(args.meta_class)});
      if (!b) return 'NOT_FOUND meta, available=' + badges.map(x=>x.textContent).join(',');
      b.parentElement.click();
      return 'clicked meta ' + {json.dumps(args.meta_class)};
    }})()
    """))
    time.sleep(1.2)

    if args.page == "configuration":
        # ConfigurationPage auto-expand la/les classe(s) de la meta-classe
        # sélectionnée (setExpandedClasses) : NE PAS cliquer sur l'en-tête
        # de la carte, ça la REPLIERAIT (comportement toggle observé).
        # Quand plusieurs classes sont chargées (ex. demo_vin = cepage +
        # region + note + bouteille), la carte voulue n'est pas forcément
        # dans le viewport de 900px : scrollIntoView sur son badge-class.
        if args.cls:
            print("scroll to class card:", evaluate(cdp, f"""
            (function() {{
              const badges = [...document.querySelectorAll('.main-content .badge-class')];
              const b = badges.find(x => x.textContent.trim() === {json.dumps(args.cls)});
              if (!b) return 'NOT_FOUND class card, available=' + badges.map(x=>x.textContent).join(',');
              b.closest('.card').scrollIntoView({{block: 'start'}});
              return 'scrolled to class card ' + {json.dumps(args.cls)};
            }})()
            """))
            time.sleep(0.8)
    elif args.cls:
        # Page navigation : pas besoin de narrower via la Sidebar (son arbre
        # meta_class est replié par défaut, le badge-class n'y est donc pas
        # rendu) - un simple scroll jusqu'au groupe de la classe visée dans
        # la liste déjà affichée (non narrowée) suffit et est plus robuste.
        print("scroll to class group:", evaluate(cdp, f"""
        (function() {{
          const badges = [...document.querySelectorAll('.main-content .badge-class')];
          const b = badges.find(x => x.textContent.trim() === {json.dumps(args.cls)});
          if (!b) return 'NOT_FOUND class group, available=' + badges.map(x=>x.textContent).join(',');
          b.closest('.card').scrollIntoView({{block: 'start'}});
          return 'scrolled to class group ' + {json.dumps(args.cls)};
        }})()
        """))
        time.sleep(0.8)

    if args.page == "diagramme":
        # Layout "force" (ECharts) : simulation physique itérative, laissée
        # tourner un peu plus longtemps pour que le graphe se stabilise
        # visuellement avant la capture (sinon noeuds encore en mouvement).
        time.sleep(2.5)

    screenshot(cdp, args.out)

    cdp.call("Page.close")
    ws.close()
    try:
        requests.get(f"{args.cdp_host}/json/close/{tab_id}")
    except requests.RequestException:
        pass


if __name__ == "__main__":
    main()
