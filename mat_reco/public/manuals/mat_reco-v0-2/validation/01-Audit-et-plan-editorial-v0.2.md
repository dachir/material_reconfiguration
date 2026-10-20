# Audit et architecture éditoriale — mat_reco v0.2

Référence : architecture fournie par l’utilisateur le 14 octobre 2026.

## Écarts de la v0.1

- Organisation par fonctions, surtout MCP : remplacée par les trois flux convergents.
- Fournisseur : commande, contrôle physique, circuits alternatifs à ajouter.
- Client : devis, services, commande, jonction atelier, livraison et facture à développer.
- Stock : distinguer Repack découpe et Repack recomposition.
- Repères de position, rôles et raisons absents : gabarit fixe obligatoire.
- Bibliothèque limitée à 14 figures : élargir et documenter toutes les provenances.
- Index Excel, storyboard, icônes et dossier de validation : à ajouter.

## Carte de navigation

Fournisseur → matière disponible → Atelier

Client → besoin dimensionné → Atelier → pièces / ouvrages disponibles → Livraison → Facture

Le Flux 3 prolonge l’Atelier par Stock / Recomposition. Les services ne sont pas des pièces à placer. Purchase Order n’est pas obligatoire dans tous les circuits.

## Table des matières retenue

- 00 — Bienvenue dans mat_reco : objectifs et fonctionnement
- 01 — Carte globale des trois flux
- 02 — Les documents ERPNext et leurs relations
- 03 — Rôles et responsabilités
- 04 — Comment lire les graphes, captures et repères visuels
- 05 — Cas pratique fil rouge : de la commande à la facture

### Flux 1 · Fournisseur

- F01 — Identifier le besoin d’approvisionnement
- F02 — Créer une commande fournisseur
- F03 — Préparer la réception physique
- F04 — Réceptionner avec Purchase Receipt
- F05 — Réceptionner via Material Receipt Plan
- F06 — Comprendre les deux circuits de réception
- F07 — Contrôler les Serial No générés
- F08 — Contrôler dimensions, épaisseur et qualité
- F09 — Vérifier le dépôt et la disponibilité

### Flux 2 · Client

- C01 — Comprendre la demande client
- C02 — Créer un devis
- C03 — Saisir dimensions et quantités
- C04 — Ajouter services et accessoires
- C05 — Définir les articles DECOUPE et OUVRAGE
- C06 — Transformer le devis en Sales Order
- C07 — Transmettre les besoins à l’atelier
- C08 — Suivre l’état de fabrication
- C09 — Vérifier les produits finis disponibles
- C10 — Préparer et soumettre Delivery Note
- C11 — Contrôler les Serial No et les dimensions livrées
- C12 — Créer Sales Invoice
- C13 — Contrôler facture, quantités et références

### Flux 3 · Atelier

- A01 — Comprendre les besoins issus des commandes
- A02 — Créer Material Cutting Plan
- A03 — Charger les commandes client
- A04 — Charger les matières disponibles
- A05 — Qualifier les plaques
- A06 — Paramétrer la découpe
- A07 — Générer et lire le plan initial
- A08 — Comprendre produits finis, chutes et déchets
- A09 — Passer en Retour Terrain
- A10 — Ouvrir Atelier UX 2.0
- A11 — Sélectionner une pièce et utiliser le menu contextuel
- A12 — Déplacer une pièce
- A13 — Tourner une pièce à 90°
- A14 — Redimensionner
- A15 — Détruire une pièce cassée
- A16 — Fusionner deux zones
- A17 — Créer une Chute en L
- A18 — Prévisualiser, confirmer et appliquer
- A19 — Identifier les besoins manquants
- A20 — Ouvrir la compensation
- A21 — Réutiliser une chute du MCP
- A22 — Utiliser une chute du stock
- A23 — Ajouter une plaque entière
- A24 — Calculer et valider la compensation
- A25 — Gérer les casses successives
- A26 — Contrôler le plan effectif
- A27 — Réinitialiser en sécurité
- A28 — Préparer la clôture et la soumission MCP

### Flux 3 · Stock / Recomposition

- S01 — Comprendre le rôle du Repack
- S02 — Créer Draft Repack depuis MCP
- S03 — Contrôler les matières consommées
- S04 — Contrôler les pièces produites
- S05 — Contrôler les chutes générées
- S06 — Comprendre les déchets
- S07 — Contrôler les surfaces
- S08 — Contrôler les coûts et valeurs
- S09 — Soumettre Stock Entry Repack
- S10 — Recomposition depuis une Sales Order
- S11 — Contrôler les composants d’un OUVRAGE
- S12 — Comprendre Material Reconfiguration historique
- S13 — Suivre les nouveaux Serial No
- S14 — Mettre les produits à disposition du Flux Client

### Exceptions

- E01 — Commande introuvable
- E02 — Matière insuffisante
- E03 — Dimensions incompatibles
- E04 — Pièce cassée
- E05 — Compensation impossible
- E06 — Chute en L non exploitable
- E07 — Conflit entre deux utilisateurs
- E08 — Serial No indisponible
- E09 — Repack refusé
- E10 — Différence de surface ou de valeur
- E11 — Annulation et réinitialisation
- E12 — Document déjà soumis

### Exercices / validation / annexes

- X01 — Réception de plaques fournisseur
- X02 — Commande avec découpe réussie
- X03 — Commande avec casse et compensation
- V01 — Checklists et décisions ouvertes
- G01 — Glossaire
- N01 — Paramétrage / circuit historique / hors périmètre
- N02 — Sources et limites de validation
- I01 — Index des captures

## Discipline documentaire

Chaque fiche : position, objectif, pourquoi, quand, rôle, document, entrées, actions, contrôles, résultat, suite, erreurs et capture ou graphe. Les fonctions déduites du code ne sont pas certifiées en production. Aucun mouvement métier ne sera soumis pour fabriquer des captures. Les formulaires non capturés en session sont reconstitués et signalés. Les décisions MCP / Repack et les options de facturation restent ouvertes.
