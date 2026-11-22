import { useEffect, useRef, useState } from 'react';
import { apiReadObjects, apiReadObject, apiWriteObject, apiDeleteObject } from '../api';
import type { ObjectSummary, ObjectDetail } from '../types';

// Action 10b (plan-mark3.md) : rendu en LECTURE SEULE d'un dashboard et de
// ses tabs (meta-classe `dashboard`, classes `dashboard`/`tab`, créée en
// 10a).
// Action 10c : ajout du CRUD (création dashboard, création/édition/
// suppression de tab) au-dessus de ce rendu lecture seule - toutes les
// actions d'écriture sont cachées (pas juste désactivées) quand
// `readOnly === true`, le rendu lecture seule de 10b reste inchangé dans ce
// cas. Le chargement dynamique des objets réellement ciblés par un tab (via
// target_meta_class/target_class) reste hors scope (action 10d).

interface DashboardPageProps {
  readOnly: boolean;
}

interface TabFormState {
  mode: 'create' | 'edit';
  id?: number;
  name: string;
  target_meta_class: string;
  target_class: string;
  dashboardId: number;
}

function getJointId(value: string | number | { joint_id: number } | undefined): number | null {
  return typeof value === 'object' && value !== null && 'joint_id' in value ? value.joint_id : null;
}

function getStringAttr(detail: ObjectDetail, name: string): string {
  const attr = detail.attributes.find((a) => a.name === name);
  if (!attr || attr.values.length === 0) return '';
  const v = attr.values[0];
  return typeof v === 'object' ? '' : String(v);
}

export default function DashboardPage({ readOnly }: DashboardPageProps) {
  const [dashboards, setDashboards] = useState<ObjectDetail[]>([]);
  const [tabs, setTabs] = useState<ObjectDetail[]>([]);
  const [selectedDashboardId, setSelectedDashboardId] = useState<number | null>(null);
  const [selectedTabId, setSelectedTabId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Erreur de mutation (création/édition/suppression) : état dédié et
  // transitoire, distinct de `error` (échec du chargement initial) pour ne
  // jamais l'écraser - cohérent avec la consigne de ne pas avaler les
  // erreurs serveur (ex. 403 RBAC tenant, 400) silencieusement.
  const [mutationError, setMutationError] = useState<string | null>(null);

  const [newDashboardName, setNewDashboardName] = useState('');
  const [tabForm, setTabForm] = useState<TabFormState | null>(null);

  const mountedRef = useRef(true);

  // Extrait du montage initial (itération 1 de 10b) pour être réutilisable
  // après chaque mutation - mécanisme Promise.allSettled inchangé (fix de
  // l'itération 2 de 10b, ne pas régresser en Promise.all).
  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const summaries = await apiReadObjects();
      const dashboardSummaries = summaries.filter(
        (o: ObjectSummary) => o.meta_class === 'dashboard' && o.class === 'dashboard'
      );
      const tabSummaries = summaries.filter(
        (o: ObjectSummary) => o.meta_class === 'dashboard' && o.class === 'tab'
      );
      const [dashboardResults, tabResults] = await Promise.all([
        Promise.allSettled(dashboardSummaries.map((o) => apiReadObject(o.id))),
        Promise.allSettled(tabSummaries.map((o) => apiReadObject(o.id))),
      ]);
      if (!mountedRef.current) return;
      const dashboardDetails = dashboardResults
        .filter((r): r is PromiseFulfilledResult<ObjectDetail> => r.status === 'fulfilled')
        .map((r) => r.value);
      const tabDetails = tabResults
        .filter((r): r is PromiseFulfilledResult<ObjectDetail> => r.status === 'fulfilled')
        .map((r) => r.value);
      setDashboards(dashboardDetails);
      setTabs(tabDetails);
      // Un seul dashboard disponible : sélection automatique. Plusieurs :
      // l'utilisateur choisit via le sélecteur ci-dessous. Aucun : état
      // vide géré par le rendu (selectedDashboardId reste null).
      if (dashboardDetails.length === 1) {
        setSelectedDashboardId(dashboardDetails[0].id);
      }
    } catch (err) {
      if (mountedRef.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    loadData();
    return () => { mountedRef.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tabs du dashboard sélectionné : ceux dont l'attribut joint-1-1
  // `dashboard` pointe (joint_id) vers selectedDashboardId (même principe
  // que getParentIds dans NavigationPage.tsx, réimplémenté ici en local -
  // ce composant ne modifie pas NavigationPage.tsx).
  const tabsForSelectedDashboard = selectedDashboardId == null
    ? []
    : tabs.filter((t) => getJointId(t.attributes.find((a) => a.name === 'dashboard')?.values[0]) === selectedDashboardId);

  const firstDashboardRenderRef = useRef(true);

  useEffect(() => {
    // Changement de dashboard sélectionné pendant qu'un formulaire de tab
    // est ouvert : le fermer pour éviter un reparentage silencieux du tab
    // en cours d'édition vers le nouveau dashboard sélectionné (cf.
    // plan-mark3.md). Ignoré au montage initial (pas de form ouvert à ce
    // stade de toute façon, mais évite un effet surprenant).
    if (firstDashboardRenderRef.current) {
      firstDashboardRenderRef.current = false;
    } else {
      setTabForm(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDashboardId]);

  useEffect(() => {
    // Changement de dashboard sélectionné : réinitialiser le tab actif s'il
    // n'appartient plus au dashboard courant (ou sélectionner le premier
    // tab disponible par défaut).
    if (tabsForSelectedDashboard.length === 0) {
      setSelectedTabId(null);
      return;
    }
    if (!tabsForSelectedDashboard.some((t) => t.id === selectedTabId)) {
      setSelectedTabId(tabsForSelectedDashboard[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDashboardId, tabs]);

  const handleCreateDashboard = async () => {
    const name = newDashboardName.trim();
    if (!name) return;
    setMutationError(null);
    try {
      const res = await apiWriteObject({ meta_class: 'dashboard', class: 'dashboard', attributes: { name } });
      setNewDashboardName('');
      await loadData();
      setSelectedDashboardId(res.id);
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : String(err));
    }
  };

  const openCreateTabForm = () => {
    if (selectedDashboardId == null) return;
    setMutationError(null);
    setTabForm({ mode: 'create', name: '', target_meta_class: '', target_class: '', dashboardId: selectedDashboardId });
  };

  const openEditTabForm = (tab: ObjectDetail) => {
    // Snapshot de dashboardId depuis l'attribut `dashboard` du tab lui-même
    // (pas depuis selectedDashboardId, qui peut changer pendant que le
    // formulaire reste ouvert - cf. plan-mark3.md, fix bug reparentage
    // silencieux) : reste correct même si le tab affiché n'appartient
    // techniquement plus au dashboard actuellement sélectionné.
    const dashboardId = getJointId(tab.attributes.find((a) => a.name === 'dashboard')?.values[0]);
    if (dashboardId == null) return;
    setMutationError(null);
    setTabForm({
      mode: 'edit',
      id: tab.id,
      name: getStringAttr(tab, 'name'),
      target_meta_class: getStringAttr(tab, 'target_meta_class'),
      target_class: getStringAttr(tab, 'target_class'),
      dashboardId,
    });
  };

  const closeTabForm = () => setTabForm(null);

  const handleSaveTab = async () => {
    if (!tabForm) return;
    const name = tabForm.name.trim();
    if (!name) {
      setMutationError('Nom du tab requis');
      return;
    }
    setMutationError(null);
    try {
      // Même convention que handleSave dans NavigationPage.tsx : un champ
      // texte laissé vide n'est pas envoyé dans "attributes" (le serveur
      // ferme un attribut actif omis - sémantique "remplacement complet",
      // cf. routes_write.py) plutôt que d'envoyer une chaîne vide.
      // dashboardId vient du snapshot pris à l'ouverture du formulaire
      // (tabForm.dashboardId), jamais du state live selectedDashboardId -
      // sinon un changement de sélection pendant l'édition reparenterait
      // silencieusement le tab au clic "Enregistrer".
      const attributes: Record<string, unknown> = {
        name,
        dashboard: { joint_id: tabForm.dashboardId },
      };
      if (tabForm.target_meta_class.trim() !== '') attributes.target_meta_class = tabForm.target_meta_class.trim();
      if (tabForm.target_class.trim() !== '') attributes.target_class = tabForm.target_class.trim();

      const payload: { id?: number; meta_class: string; class: string; attributes: Record<string, unknown> } = {
        meta_class: 'dashboard',
        class: 'tab',
        attributes,
      };
      if (tabForm.mode === 'edit' && tabForm.id != null) payload.id = tabForm.id;

      const res = await apiWriteObject(payload);
      const savedId = tabForm.mode === 'edit' && tabForm.id != null ? tabForm.id : res.id;
      setTabForm(null);
      await loadData();
      setSelectedTabId(savedId);
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDeleteTab = async (tab: ObjectDetail) => {
    const label = getStringAttr(tab, 'name') || `#${tab.id}`;
    if (!window.confirm(`Supprimer le tab "${label}" ?`)) return;
    setMutationError(null);
    try {
      await apiDeleteObject(tab.id);
      if (tabForm?.id === tab.id) setTabForm(null);
      await loadData();
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : String(err));
    }
  };

  if (loading) return <div className="card">Chargement…</div>;
  if (error) return <div className="card">Erreur : {error}</div>;

  const selectedTab = tabsForSelectedDashboard.find((t) => t.id === selectedTabId) || null;

  return (
    <div>
      <div className="card">
        <h2>Dashboard</h2>
        {dashboards.length === 0 && <p>Aucun dashboard configuré.</p>}
        {dashboards.length > 1 && (
          <div className="form-group">
            <label>Dashboard</label>
            <select
              value={selectedDashboardId ?? ''}
              onChange={(e) => setSelectedDashboardId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">-- Choisir --</option>
              {dashboards.map((d) => (
                <option key={d.id} value={d.id}>{getStringAttr(d, 'name') || `#${d.id}`}</option>
              ))}
            </select>
          </div>
        )}
        {!readOnly && (
          <div className="form-group" style={{ marginTop: 12 }}>
            <label>Nouveau dashboard</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="text"
                placeholder="Nom du dashboard"
                value={newDashboardName}
                onChange={(e) => setNewDashboardName(e.target.value)}
              />
              <button className="btn btn-primary" onClick={handleCreateDashboard} disabled={!newDashboardName.trim()}>
                Créer
              </button>
            </div>
          </div>
        )}
        {mutationError && <p style={{ color: 'var(--color-danger, #c0392b)' }}>Erreur : {mutationError}</p>}
      </div>

      {selectedDashboardId != null && (
        <div className="card">
          {tabsForSelectedDashboard.length === 0 ? (
            <p>Aucun tab configuré pour ce dashboard.</p>
          ) : (
            <div className="btn-group" style={{ flexWrap: 'wrap' }}>
              {tabsForSelectedDashboard.map((t) => (
                <button
                  key={t.id}
                  className={`btn ${selectedTabId === t.id ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => {
                    if (tabForm != null && tabForm.mode === 'edit' && tabForm.id !== t.id) setTabForm(null);
                    setSelectedTabId(t.id);
                  }}
                >
                  {getStringAttr(t, 'name') || `#${t.id}`}
                </button>
              ))}
            </div>
          )}

          {!readOnly && (
            <div style={{ marginTop: 12 }}>
              {tabForm == null ? (
                <button className="btn btn-secondary" onClick={openCreateTabForm}>+ Nouveau tab</button>
              ) : (
                <div className="form-group">
                  <label>{tabForm.mode === 'create' ? 'Nouveau tab' : `Modifier le tab #${tabForm.id}`}</label>
                  <input
                    type="text"
                    placeholder="Nom"
                    value={tabForm.name}
                    onChange={(e) => setTabForm({ ...tabForm, name: e.target.value })}
                  />
                  <input
                    type="text"
                    placeholder="target_meta_class"
                    value={tabForm.target_meta_class}
                    onChange={(e) => setTabForm({ ...tabForm, target_meta_class: e.target.value })}
                  />
                  <input
                    type="text"
                    placeholder="target_class"
                    value={tabForm.target_class}
                    onChange={(e) => setTabForm({ ...tabForm, target_class: e.target.value })}
                  />
                  <div className="btn-group" style={{ marginTop: 8 }}>
                    <button className="btn btn-primary" onClick={handleSaveTab}>Enregistrer</button>
                    <button className="btn btn-secondary" onClick={closeTabForm}>Annuler</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {selectedTab && (
            <div style={{ marginTop: 16 }}>
              {/* Contenu du tab : uniquement ses champs statiques
                  (target_meta_class/target_class) en texte, pas de
                  chargement des objets de la classe cible - sélection
                  dynamique des sous-objets = action 10d, hors scope ici. */}
              <p>
                Cible : classe <code>{getStringAttr(selectedTab, 'target_class') || '(non renseignée)'}</code>
                {' '}(meta-classe <code>{getStringAttr(selectedTab, 'target_meta_class') || '(non renseignée)'}</code>)
              </p>
              {!readOnly && (
                <div className="btn-group">
                  <button className="btn btn-secondary" onClick={() => openEditTabForm(selectedTab)}>Modifier</button>
                  <button className="btn btn-secondary" onClick={() => handleDeleteTab(selectedTab)}>Supprimer</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
