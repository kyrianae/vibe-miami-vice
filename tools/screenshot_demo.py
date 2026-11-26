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

  # --layer (sans --meta-class) : narrow par le filtre Layers de la Sidebar
  # (chips sur Configuration/Navigation, combo multi-select sur Diagramme).
  # Attention : purement additif (comportement IHM existant, non modifié
  # ici) - une classe SANS layer reste toujours visible quel que soit le
  # filtre (cf. schema.json, champ 'layers'), donc --layer seul ne suffit
  # PAS à isoler une démo si d'autres classes du système n'ont aucun layer
  # (cas réel de ce dépôt) : voir --only-classes ci-dessous pour ce besoin.
  python3 tools/screenshot_demo.py \\
    --token-file /chemin/vers/token.txt \\
    --page navigation --layer demo \\
    --out doc/demo-xxx/navigation.png

  # --only-classes (page diagramme uniquement) : clique "Rien" (masque
  # toutes les classes) puis ré-active uniquement les chips listées -
  # utile quand les classes d'une même démo sont réparties sur plusieurs
  # meta-classes (ex. demo_kafka + cmdb, correctif post-revue action 3b,
  # plan-mark4.md) et qu'un simple --meta-class exclurait à tort les
  # classes situées dans l'autre meta-classe (filtre selectedMetaClass dur,
  # contrairement à --layer qui est additif, cf. ci-dessus).
  python3 tools/screenshot_demo.py \\
    --token-file /chemin/vers/token.txt \\
    --page diagramme \\
    --only-classes vm,type_donnee,base_donnees,bus_kafka,application,reverse_proxy \\
    --out doc/demo-kafka/diagramme.png

  # --expand-class (page navigation uniquement) : NavigationPage.tsx
  # auto-expand en principe tous les groupes au chargement (effet sur
  # filtered.map(id).join(',')), mais ce n'est pas fiable pour une
  # meta-classe à beaucoup d'objets/classes (ex. organisation, 75 objets/8
  # classes - action 3c, plan-mark4.md) : le groupe visé est resté
  # collapsed (chevron ▼) malgré --class. --expand-class force un clic sur
  # l'en-tête du groupe (toggle), mais seulement si le chevron affiche
  # encore ▼ au moment du clic (idempotent, ne collapse jamais un groupe
  # déjà expand par l'auto-expand - sûr à combiner avec --class même quand
  # l'auto-expand fonctionne, comme en 3a/3b).
  python3 tools/screenshot_demo.py \\
    --token-file /chemin/vers/token.txt \\
    --page navigation --meta-class organisation --class poste --expand-class poste \\
    --out doc/demo-organigramme/navigation.png
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
    p.add_argument("--meta-class", default=None, help="meta_class à sélectionner dans la Sidebar (badge-meta). Omis si --layer est utilisé à la place.")
    p.add_argument("--class", dest="cls", default=None,
                   help="Nom de classe à sélectionner en plus (page navigation uniquement, narrow la liste)")
    p.add_argument("--layer", default=None,
                   help="Layer à sélectionner dans le filtre Layers de la Sidebar (alternative à --meta-class quand les classes d'une démo sont réparties sur plusieurs meta-classes)")
    p.add_argument("--attr", default=None,
                   help="Page configuration uniquement : nom d'attribut sur lequel scroller en complément de --class (classe trop riche pour tenir dans le viewport, l'attribut visé n'est pas forcément dans les premières lignes)")
    p.add_argument("--only-classes", default=None,
                   help="Page diagramme uniquement : liste de classes séparées par des virgules à montrer exclusivement (clique 'Rien' puis ré-active ces chips), alternative à --meta-class quand les classes d'une démo sont réparties sur plusieurs meta-classes")
    p.add_argument("--expand-class", default=None,
                   help="Page navigation uniquement : force l'expansion du groupe de cette classe (clic idempotent sur l'en-tête si le chevron affiche encore ▼) - utile quand l'auto-expand de NavigationPage.tsx n'a pas eu l'effet attendu (meta-classe à beaucoup d'objets/classes)")
    p.add_argument("--out", required=True, help="Chemin du PNG de sortie")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=900)
    args = p.parse_args()
    if not args.meta_class and not args.layer and not args.only_classes:
        p.error("--meta-class, --layer ou --only-classes requis")

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
    # Filtre Layers persisté en localStorage (frontend/src/App.tsx
    # SELECTED_LAYERS_STORAGE_KEY) : purgé à chaque run pour un état de
    # départ déterministe, sinon un --layer ré-exécuté deux fois de suite
    # (même profil Chrome persistant entre invocations) TOGGLE le filtre à
    # tort (déjà sélectionné par le run précédent -> ce clic le désactive).
    print("clear selected layers:", evaluate(cdp, "localStorage.removeItem('miami-vice-selected-layers'); 'ok'"))

    # Reload pour démarrer authentifié (Navbar lit getAuthToken() au montage).
    goto(cdp, args.frontend_url)
    time.sleep(1.5)
    print("token present after reload:", evaluate(cdp, "!!localStorage.getItem('miami-vice-auth-token')"))

    label = {"configuration": "Configuration", "navigation": "Navigation", "diagramme": "Diagramme"}[args.page]
    result = evaluate(cdp, f"""
    (function() {{
      const b = [...document.querySelectorAll('nav.navbar button')].find(x => x.textContent.trim() === '{label}');
      if (!b) return 'NOT_FOUND';
      b.click();
      return 'clicked:' + b.textContent;
    }})()
    """)
    print("click nav:", result)
    if isinstance(result, str) and result.startswith("NOT_FOUND"):
        raise RuntimeError(result)
    time.sleep(1.0)

    if args.meta_class:
        result = evaluate(cdp, f"""
        (function() {{
          const badges = [...document.querySelectorAll('.sidebar .badge-meta')];
          const b = badges.find(x => x.textContent.trim() === {json.dumps(args.meta_class)});
          if (!b) return 'NOT_FOUND meta, available=' + badges.map(x=>x.textContent).join(',');
          b.parentElement.click();
          return 'clicked meta ' + {json.dumps(args.meta_class)};
        }})()
        """)
        print("click meta:", result)
        if isinstance(result, str) and result.startswith("NOT_FOUND"):
            raise RuntimeError(result)
        time.sleep(1.2)

    if args.layer:
        if args.page == "diagramme":
            result = evaluate(cdp, f"""
            (function() {{
              const sel = document.querySelector('.sidebar select[multiple]');
              if (!sel) return 'NOT_FOUND layer select';
              const opt = [...sel.options].find(o => o.value === {json.dumps(args.layer)});
              if (!opt) return 'NOT_FOUND layer option, available=' + [...sel.options].map(o => o.value).join(',');
              opt.selected = true;
              sel.dispatchEvent(new Event('change', {{bubbles: true}}));
              return 'selected layer ' + {json.dumps(args.layer)};
            }})()
            """)
        else:
            result = evaluate(cdp, f"""
            (function() {{
              const spans = [...document.querySelectorAll('.sidebar span[title]')].filter(x => x.title.includes('filtre'));
              const b = spans.find(x => x.textContent.trim() === {json.dumps(args.layer)});
              if (!b) return 'NOT_FOUND layer chip, available=' + spans.map(x => x.textContent).join(',');
              b.click();
              return 'clicked layer ' + {json.dumps(args.layer)};
            }})()
            """)
        print("select layer:", result)
        if isinstance(result, str) and result.startswith("NOT_FOUND"):
            raise RuntimeError(result)
        time.sleep(1.2)

    if args.page == "configuration":
        # ConfigurationPage auto-expand la/les classe(s) de la meta-classe
        # sélectionnée (setExpandedClasses) : NE PAS cliquer sur l'en-tête
        # de la carte, ça la REPLIERAIT (comportement toggle observé).
        # Quand plusieurs classes sont chargées (ex. demo_vin = cepage +
        # region + note + bouteille), la carte voulue n'est pas forcément
        # dans le viewport de 900px : scrollIntoView sur son badge-class.
        if args.cls:
            result = evaluate(cdp, f"""
            (function() {{
              const badges = [...document.querySelectorAll('.main-content .badge-class')];
              const b = badges.find(x => x.textContent.trim() === {json.dumps(args.cls)});
              if (!b) return 'NOT_FOUND class card, available=' + badges.map(x=>x.textContent).join(',');
              b.closest('.card').scrollIntoView({{block: 'start'}});
              return 'scrolled to class card ' + {json.dumps(args.cls)};
            }})()
            """)
            print("scroll to class card:", result)
            if isinstance(result, str) and result.startswith("NOT_FOUND"):
                raise RuntimeError(result)
            time.sleep(0.8)

            if args.attr:
                result = evaluate(cdp, f"""
                (function() {{
                  const inputs = [...document.querySelectorAll('.main-content input')];
                  const inp = inputs.find(x => x.value === {json.dumps(args.attr)});
                  if (!inp) return 'NOT_FOUND attr row';
                  inp.closest('div').scrollIntoView({{block: 'center'}});
                  return 'scrolled to attr ' + {json.dumps(args.attr)};
                }})()
                """)
                print("scroll to attr row:", result)
                if isinstance(result, str) and result.startswith("NOT_FOUND"):
                    raise RuntimeError(result)
                time.sleep(0.8)
    elif args.cls:
        # Page navigation : pas besoin de narrower via la Sidebar (son arbre
        # meta_class est replié par défaut, le badge-class n'y est donc pas
        # rendu) - un simple scroll jusqu'au groupe de la classe visée dans
        # la liste déjà affichée (non narrowée) suffit et est plus robuste.
        result = evaluate(cdp, f"""
        (function() {{
          const badges = [...document.querySelectorAll('.main-content .badge-class')];
          const b = badges.find(x => x.textContent.trim() === {json.dumps(args.cls)});
          if (!b) return 'NOT_FOUND class group, available=' + badges.map(x=>x.textContent).join(',');
          b.closest('.card').scrollIntoView({{block: 'start'}});
          return 'scrolled to class group ' + {json.dumps(args.cls)};
        }})()
        """)
        print("scroll to class group:", result)
        if isinstance(result, str) and result.startswith("NOT_FOUND"):
            raise RuntimeError(result)
        time.sleep(0.8)

    if args.page == "navigation" and args.expand_class:
        result = evaluate(cdp, f"""
        (function() {{
          const badges = [...document.querySelectorAll('.main-content .badge-class')];
          const b = badges.find(x => x.textContent.trim() === {json.dumps(args.expand_class)});
          if (!b) return 'NOT_FOUND class group, available=' + badges.map(x=>x.textContent).join(',');
          const header = b.closest('h2').parentElement;
          const chevron = header.querySelector('span[style*="font-size: 14px"]') ||
            [...header.querySelectorAll('span')].find(s => s.textContent === '▼' || s.textContent === '▲');
          if (chevron && chevron.textContent.trim() === '▼') {{
            header.click();
            return 'expanded ' + {json.dumps(args.expand_class)};
          }}
          return 'already expanded (or chevron not found) ' + {json.dumps(args.expand_class)};
        }})()
        """)
        print("expand class group:", result)
        if isinstance(result, str) and result.startswith("NOT_FOUND"):
            raise RuntimeError(result)
        time.sleep(1.0)

    if args.page == "diagramme" and args.only_classes:
        result = evaluate(cdp, """
        (function() {
          const btns = [...document.querySelectorAll('.diagram-filter-btn')];
          const hideAll = btns.find(x => x.textContent.trim() === 'Rien');
          if (!hideAll) return 'NOT_FOUND bouton Rien';
          hideAll.click();
          return 'clicked Rien';
        })()
        """)
        print("hide all classes:", result)
        if isinstance(result, str) and result.startswith("NOT_FOUND"):
            raise RuntimeError(result)
        time.sleep(0.5)

        for cls_name in args.only_classes.split(","):
            cls_name = cls_name.strip()
            result = evaluate(cdp, f"""
            (function() {{
              const chips = [...document.querySelectorAll('.diagram-chip')];
              const b = chips.find(x => x.textContent.trim().startsWith({json.dumps(cls_name)})
                && /^[0-9]/.test(x.textContent.trim().slice({len(cls_name)})));
              if (!b) return 'NOT_FOUND chip, available=' + chips.map(x=>x.textContent.trim()).join(',');
              b.click();
              return 'enabled chip ' + {json.dumps(cls_name)};
            }})()
            """)
            print("enable chip:", result)
            if isinstance(result, str) and result.startswith("NOT_FOUND"):
                raise RuntimeError(result)
            time.sleep(0.3)

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
