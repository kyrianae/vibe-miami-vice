# 8. Dépendances déclarées mais non exploitées par le code

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

- `jsonschema` (backend) : dépendance présente, jamais utilisée (§3.2, §4.5).
- `sql_constraint` (modèle JSON) : champ documenté dans `model/schema.json`
  et renseigné dans `model/reseau.json` (`"UNIQUE VALUE"` sur `adresse_ip`),
  mais **jamais lu ni appliqué** par `app.py` — aucune contrainte SQL n'est
  générée dynamiquement à partir de cette valeur ; la table `attribute_value`
  ne porte aucune contrainte d'unicité par attribut.
- `constraint` (regex de validation d'un attribut `string`) : également
  jamais vérifié côté backend à l'écriture (`POST /api/write/object`,
  `PUT /api/write/attribute/...`) — seul le frontend l'affiche comme
  placeholder indicatif dans les formulaires, sans bloquer la saisie.

# 9. Récapitulatif des anomalies constatées (par gravité)

1. **Bloquant** — `backend/app.py` ne compile pas (`IndentationError` ligne
   97, dans `get_classes_by_meta_class`) : l'application Flask ne démarre
   pas du tout dans l'état actuel du dépôt.
2. **Bloquant fonctionnel** (une fois le point 1 corrigé) —
   `GET /api/read/object/<id>` ne retourne jamais les attributs d'un objet
   existant (code de construction de la réponse placé par erreur sous
   `if not obj:`) ; il renvoie une erreur 500 pour tout objet présent en
   base et 404 pour tout objet absent.
3. **Fonctionnel** — `displayname` n'est jamais renvoyé par les 3 endpoints
   de lecture de classes (`/api/read/class`, `/api/read/class/<id>`,
   `/api/read/<meta_class>`), rendant inopérant le gabarit d'affichage
   pourtant bien stocké en base et bien restitué à l'écriture.
4. **Fonctionnel** — l'édition inline (cellule scalaire ou jointure 1-1)
   de la page Navigation n'effectue aucune écriture réelle
   (`saveInlineEdit` dans `NavigationPage.tsx`), malgré un message de
   succès affiché à l'utilisateur ; `apiWriteAttribute`/`PUT
   /api/write/attribute/...` existe côté client et serveur mais n'est
   jamais relié.
5. **Absence de contrôle** — aucune validation du schéma JSON
   (`model/schema.json`) n'est appliquée nulle part (ni à l'écriture des
   définitions, ni au chargement `/api/init`) ; aucune validation de
   `constraint`/`sql_constraint` n'est appliquée à l'écriture des objets ;
   aucune vérification que la `meta_class`/`class` d'un objet écrit via
   `POST /api/write/object` corresponde à une définition existante.
6. **Absence de fonctionnalité** — aucune route de suppression (objet,
   classe ou meta-classe) n'existe, bien que le schéma SQL soit prévu pour
   (`ON DELETE CASCADE`).
7. **Absence de sécurité** — aucune authentification/autorisation sur
   l'API ; le toggle lecture seule du frontend est un simple artifice
   d'interface, sans portée serveur.
8. **Cohérence modèle** — les fichiers `model/personnes.json` et
   `model/reseau.json` contiennent une clé `$schema` non déclarée dans
   `model/schema.json` (`additionalProperties: false`), ce qui les rendrait
   eux-mêmes invalides si la validation décrite au point 5 était un jour
   activée telle quelle.

> Ces deux sections (§8-§9) restent un instantané figé de l'audit du
> 2026-11-07 — bugs depuis corrigés en Mark 1/Mark 2, non remis à jour ici
> pour préserver la trace de l'état initial (voir
> [`07-roadmap.md`](07-roadmap.md) pour le statut réel actuel).
