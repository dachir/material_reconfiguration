# Déplacement entre plaques et curseurs UX 2.0

Sélectionner une pièce, choisir **Déplacer**, changer de plaque et sélectionner
une chute compatible. Lorsque **Allow Rotation** est activé sur le MCP, le mode
Automatique essaie l’orientation actuelle puis une rotation de 90°. Le panneau
permet également de choisir explicitement l’orientation. Les dimensions sont
validées côté serveur; une chute en L conserve sa zone déjà retirée.

Le déplacement conserve l’identité commerciale de la pièce et libère sa zone
source. Les opérations canoniques sont enregistrées dans les incidents et
l’arbre effectif, sans recalcul global des plaques. Le marqueur
`ux20_incidents_resolved` évite de rejouer les anciens déplacements.

Les curseurs de l’atelier suivent l’action active : déplacement, symbole de
fusion ou forme en L. Les cibles incompatibles affichent le curseur
`not-allowed`. Annuler ou confirmer rétablit le curseur habituel. Les curseurs
fusion/L utilisent des SVG locaux, avec un curseur de précision en repli.

Vérifications : 82 tests Python, 38 tests Node et tests Chromium des curseurs,
du déplacement inter-plaque avec rotation, de la compensation et du cycle de
vie de l’aperçu. Les essais navigateur utilisent des documents simulés sans
écriture métier. Un essai Frappe sur des copies en mémoire valide aussi le hook
before_save et les lignes Repack; aucune sauvegarde métier réelle n’a été faite.
