inference / machine learning sur le graphe d objets, en integrant le projet a cote comme datasource : apprentissage multi-dimensionnel sur les attributs des objets, propagation des valeurs inferees via les jointures (joint-1-1/joint-1-n) existantes — possible une fois datasource ml + import de data + attribut "valeur inferee" faits (ajouté a tocheck.md)

dashboard de monitoring concret (requetes en direct, pas juste affichage) — possible une fois type datasource + type attribut query instant/query vector faits

dashboard de monitoring

vue metier dediee par role sur le meme socle de donnees (ex: vue ticketing en lecture seule sur les serveurs, vue cmdb complete pour les admins) — possible une fois framework de dashboard/tabs édités + generation de display avec read-only partiel faits

pipeline d ingestion automatisé et recurrent (binding champs source -> attributs + schedule), alimente aussi le cas inference ml ci-dessus — possible une fois outil d ingestion avec binding + schedule d imports faits

cmdb avec supervision integree, renforcé par datasource prometheus/postgresql + icone de classe + logo par objet pour les diagrammes

cmdb

coffre-fort documentaire / GED, versions de fichiers par classe/id/attribut — possible une fois type attribut fichier + stockage (s3 ou a plat) fait

gestionnaire de secrets / vault de credentials — possible une fois type attribut secret/password (valeur masquée) fait

inventaire physique avec photos (parc materiel, immobilier, flotte vehicules) — possible une fois type attribut image fait

outil de gestion de ticket, renforcé par fichier (pieces jointes) + icone (type de ticket) + manque encore un type select/enum pour le statut/workflow (ajouté a tocheck.md)

outils de gestion de ticket

outil de bibliotheque/vinotheque, renforcé par image (couverture/etiquette) + csv (import catalogue en masse)

outil de gestion de bibliotehque ou vinotheque ....

migration / interconnexion en masse avec un outil existant via import csv — possible une fois type attribut csv fait
