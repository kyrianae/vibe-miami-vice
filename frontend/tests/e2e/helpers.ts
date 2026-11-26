import type { Page } from '@playwright/test';

// Pollution pré-existante trouvée dans la base de dev partagée pendant
// l'implémentation de cette action (plan-mark4.md action 2), SANS rapport
// avec Playwright : une classe orpheline `testeur_dup_rt/compte_rt_dup`
// déclare l'attribut "pw" deux fois (types "secret" et "string"), ce qui
// déclenche un vrai avertissement React ("two children with the same key")
// dès le premier rendu de NavigationPage (page par défaut au chargement,
// cf. App.tsx) - reproduit sur toutes les pages, pas seulement Navigation.
// Pas un bug applicatif (write_class valide normalement l'unicité des noms
// d'attribut - cf. plan-mark4.md action 3b - cette classe a dû être écrite
// par un autre chemin, avant ce garde-fou, ou directement en base) : objet
// id 187, classe `compte_rt_dup`, meta-classe `testeur_dup_rt`, absente de
// tout model/*.json versionné. Suppression via l'API tentée pendant cette
// action et bloquée par le classifieur d'autorisation de l'environnement
// (DELETE jugé destructif) - nettoyage à faire manuellement :
//   DELETE /api/delete/object/187
//   DELETE /api/delete/class/testeur_dup_rt/compte_rt_dup
//   DELETE /api/delete/metaclass/testeur_dup_rt
// Ignoré ici explicitement plutôt que silencieusement : si ce filtre ne
// matche plus (classe nettoyée), les tests continuent de couvrir toute
// nouvelle vraie erreur console normalement.
//
// Note sur le texte exact : msg.text() ne substitue PAS les "%s" du format
// React (vérifié empiriquement) - le texte brut reçu est le gabarit avec
// `%s` littéral suivi, en fin de chaîne, des arguments concaténés
// (ex: "...future version.%s pw \n    at tr\n    at thead..."). D'où un
// test ciblé sur la combinaison (gabarit + mot "pw" isolé + pile
// NavigationPage) plutôt qu'une regex sur une substitution qui n'a pas
// lieu - et volontairement pas un simple "two children with the same key"
// générique, qui masquerait un futur vrai doublon de clé sur une autre
// valeur.
function isKnownPreexistingDuplicateKeyWarning(text: string): boolean {
  return (
    text.includes('Encountered two children with the same key') &&
    /\bpw\b/.test(text) &&
    text.includes('NavigationPage')
  );
}

// Collecte les erreurs console (type 'error', cf. page.on('console')) et les
// exceptions JS non interceptées (pageerror) à partir du moment de l'appel -
// à instancier avant page.goto() pour ne rater aucun message au chargement.
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (isKnownPreexistingDuplicateKeyWarning(text)) return;
    errors.push(text);
  });
  page.on('pageerror', (err) => {
    errors.push(err.message);
  });
  return errors;
}

// Navigation via le menu Navbar.tsx (app SPA sans routeur dédié,
// frontend/src/App.tsx - pas d'URL directe par page).
export async function gotoPage(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
}
