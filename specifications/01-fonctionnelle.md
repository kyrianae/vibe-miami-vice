# 1. Objectif du projet

> Fait partie de [`specifications/`](README.md) — voir l'index pour le mapping des sections.

Miami Vice est un **modélisateur de données générique** : il permet de définir
un schéma de données (meta-classes → classes → attributs typés, avec
jointures 1-1 et 1-N entre objets) sous forme de JSON, de le charger dans
PostgreSQL, puis de créer/lire/modifier des instances (« objets ») conformes
à ce schéma via une API REST Flask et une interface React.

Le modèle n'est pas figé dans des tables SQL métier : il est entièrement
dynamique — toute entité (« classe ») et ses attributs sont décrits dans des
documents JSON stockés en base, interprétés à la volée par le backend et le
frontend. Deux exemples de domaines sont fournis (`model/personnes.json` :
personnes, rôles, groupes ; `model/reseau.json` : adresses IP, VLAN).
