# 0. Avertissement — état réel du code au moment de l'audit

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

Le fichier `backend/app.py` contient actuellement une **erreur de syntaxe
Python** (`IndentationError`) dans la fonction `get_classes_by_meta_class`
(route `GET /api/read/<meta_class>`, ligne 97) :

```python
cur.execute(
        "SELECT id, meta_class, data FROM definition WHERE meta_class = %s",
        (meta_class,)
    )
    row = cur.fetchone()      # <-- indentation invalide (12 espaces au lieu de 8)
```

`python3 -c "import ast; ast.parse(open('backend/app.py').read())"` échoue avec
`IndentationError: unexpected indent` à cette ligne. Conséquence concrète :
**le module `app.py` ne peut pas être importé**, donc ni `flask run`, ni le
`gunicorn ... app:app` lancé par `backend/Dockerfile` ne peuvent démarrer
l'application. Dans l'état actuel du dépôt, le conteneur `backend` ne sert
aucune requête — toutes les routes documentées ci-dessous sont donc décrites
d'après la lecture du code (comportement *voulu*), avec mention explicite des
bugs logiques supplémentaires qui subsisteraient même une fois cette erreur de
syntaxe corrigée.
