je voudrais un type datsource, peut etre passer par une defintiion json 
puis meta class ; prometheus, postrgesql 

integration du projet a cote (inference machine learning) comme nouveau type de datasource, au meme titre que prometheus/postgresql

apprentissage multi-dimensionnel : prendre les attributs des objets (toutes classes confondues) comme dimensions d entree du modele

propagation des valeurs inferees via le graphe de jointures existant (joint-1-1/joint-1-n) comme support de propagation

attribut de type "valeur inferee" (resultat du modele ml, a distinguer d une valeur saisie a la main)

import de data depuis/vers ce projet ml pour alimenter l apprentissage

type d attribut query instant
type d attribut query vector  qui prend debut fin 

framework de dashboard / affichage configurable, avec possibilité d ajouter des tabs édités dans l ihm

generer des displays differents a partir des tabs édités, en pouvant selectionner la liste de sous-objets affichés et forcer le read-only sur certaines parties (exemple : affichage ticketing qui ne permet pas l ajout de serveur)

outil d ingestion avec binding (mapping champs source -> attributs)

workflow / capacité a scheduler les imports

definir comment on peut stocker des fichier , s3 ou a plat ? avec arborescence /class/id/attribut/fichiers de version ....

ajouter le type d attribut fichier

le type d attribut image (accepté jpg svg png)

sur un objet d une classe qui a un logo on peut surcharger le logo
on peut selectionner pami tous les logos deja presents ou importer un ficheir 
ce logo ser utilisé dans les diagrammes  

pour une classe on peut definir si il a une icone
selection d icone par defaut quand actif 

type d attribut select/enum avec liste de valeurs fixe (statut, priorité...) pour workflow type ticket, manque pour l instant

ajouter un type d attribut secret ou password u peut etre un flag qui dit que la valeur est masquée*

type d attribut csv
   avec attribut separateur

je trouve aue app.py deviens gros 
splitter ou faire une des classes, que lequipe porpose des decoupages 
