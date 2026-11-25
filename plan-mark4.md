# Plan d'action — Mark 4 — suite des corrections et évolutions de miami-vice

> **Mark 4** : fait suite à [`finished plan/plan-mark3.md`](finished%20plan/plan-mark3.md)
> (clos le 2026-11-25). Une seule action était reportée de Mark 3 — l'action
> 11 (outil d'ingestion avec binding), volontairement non traitée sur
> demande explicite de l'utilisateur. Sa conception complète est reprise en
> annexe de ce fichier (tout en bas) à titre de référence historique — **pas
> comme une action validée** : le point 6 ci-dessous (ajouté par
> l'utilisateur) demande explicitement une démarche interactive avant de la
> formaliser.
>
> Le contenu qui suit (points 0 à 6) est le brouillon de travail déposé
> directement par l'utilisateur dans ce fichier pendant que Mark 3 se
> clôturait — **conservé mot pour mot, rien reformulé ni étoffé**. Plusieurs
> points sont explicitement marqués comme nécessitant une « démarche
> interactive » (points 3, 4, 6) : conformément à la convention établie,
> cela signifie poser des questions à l'utilisateur pour définir le point
> avant de l'implémenter — pas concevoir seul puis faire valider.

0)
Optimisation travail 

analyse la conf des agents
le configuaiton est elle coherente; eut elle etre optimiser 
chacun devarit etre dasn le top 01 de son metier 

et succintement les docs et plan 
sont ils trop verbeux, ou dense , ou parasité par des inforamation historique ce qui alourdi les traitements  ?

100% of your usage came from subagent-heavy sessions
Each subagent runs its own requests. Be deliberate about spawning them — and consider configuring a cheaper model for simpler subagents.
47% of your usage was at >150k context
Longer sessions are more expensive even when cached. /compact mid-task, /clear when switching to new tasks.
29% of your usage came from sessions active for 8+ hours
These are often background/loop sessions. Continuous usage can add up quickly so make sure it is intentional.
20% of your usage came from subagents under "general-purpose"
If this runs frequently, consider configuring its subagents with a cheaper model or tightening their prompts.
Subagents
% of usage
general-purpose
20%
worker
17%
orchestrateur
10%
pessimiste
7%
testeur
4%
candide
2%
testeur-global
2%

peux tu configurer les modelesde chaque agent ?



1)
ajout de selenium pour tests ihm 
a discuter

2)
ajout documentation mode d emploi avec snapshot
dans un premier temps creation de modele 
exemple bouteille de vin 
avec attribut cepage annee 
cave / vigneron 
AOC .... 

et autre exemple 
plus technique ou professionnel 
derveur appli ( 2 3 appli avec un kafka au milieu avec de la data , datatype1 datatype2 consommateur producteur db fronten backend des vm peut etre de la redondance et de reverse proxy ou loadbalancer)
ajouter 3 4 objets et montrer el a creation d une instance d objet de chaque coté

un orgnaigramme d une holding a 2 3 societe et des structure de 5 10 personne chacune a 23 niveaux 

peut etre splitter ce point en plusieurs morceaux 

3)
champ conditionnel 
indexer l affichage d un champ sur la valeur d un autre ou sur calcul 
faire une demarche interactive pour la definition 

4)
sur les secret ajouter un bouton oeil dasn l ihm qui permet de le voir 
cela amene a une authent a definir avec une demarche interactive pour voir ce qu il est possible de faire avec keycloack 
definir qui peut voir quoi dqns la configuraiton de la classe ? peut etre 

5)
ex choix de salle : choix en cascad Salle batiment etage
la salle a tous les element chaine d enfant 
attention a suppression d un element

| 6 | Outil d'ingestion avec binding | ⬜ à faire avec demarche interactive  |

---

## Annexe — conception antérieure de l'action 11 de `plan-mark3.md` (référence historique, pas une action validée)

> Reprise intégrale, sans changement, du contenu technique écrit dans
> `plan-mark3.md` (actions close le 2026-11-25) pour ne pas perdre le
> travail de conception déjà fait — conformément à la règle du plan de ne
> jamais supprimer silencieusement du contenu. **Ne pas considérer comme
> prête à implémenter telle quelle** : le point 6 ci-dessus demande
> explicitement une démarche interactive avec l'utilisateur avant de
> formaliser cette action pour de bon — ces questions n'ont pas encore été
> posées.

- **Problème** : pas d'outil générique de mapping champs source →
  attributs.
- **Correctif envisagé à l'époque** (conception `specifications/
  07-roadmap.md` §10.13, document toujours présent, pas supprimé) :
  définition d'un mapping/binding (format probablement JSON) décrivant
  source → champ → attribut cible d'une classe ; réutilisation du type
  `csv` existant (actions 2-3 de Mark 3) comme première source d'entrée
  possible, ou upload direct ; pas d'exécution ni de scheduler dans cette
  action (ça resterait une idée séparée, jamais engagée). Point resté
  ouvert à l'époque, jamais tranché : où stocker la config de binding —
  nouvelle classe du modèle dynamique (cohérence à chercher avec le
  framework dashboard de Mark 3, qui a le même besoin de stocker de la
  config applicative, pas des objets métier) ?
- **Effort estimé à l'époque** : élevé (difficulté 4/4, fondation
  réutilisable).
- **Fichiers envisagés à l'époque** : rien n'a jamais été codé pour cette
  action — tout reste à déterminer, y compris à la lumière de la démarche
  interactive demandée au point 6.



