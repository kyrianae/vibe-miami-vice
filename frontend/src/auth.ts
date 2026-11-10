// Décodage JWT côté client (RBAC multi-tenant, plan.md action 11).
//
// ATTENTION : les rôles/tenants décodés ici viennent du token Keycloak
// (autorisation d'accès à l'API) — à ne jamais confondre avec les classes
// métier "role"/"groupe" du modèle applicatif (model/personnes.json), qui
// sont des objets métier ordinaires sans rapport avec les droits d'accès.
//
// Pas de dépendance ajoutée (ex. jwt-decode) : un simple décodage base64url
// du payload suffit ici, ce token n'est jamais vérifié côté client (seule
// la signature vérifiée côté serveur fait foi) - on ne fait que lire des
// informations déjà publiques dans le payload pour adapter l'UI.

export interface AuthInfo {
  roles: string[];
  tenants: string[];
  isGlobalAdmin: boolean;
  isTenantAdmin: boolean;
  isTenantReadonly: boolean;
}

const RBAC_ROLES = ['global-admin', 'tenant-admin', 'tenant-readonly'];

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64Url = token.split('.')[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function defaultAuthInfo(overrides: Partial<AuthInfo> = {}): AuthInfo {
  return {
    roles: [],
    tenants: [],
    isGlobalAdmin: false,
    isTenantAdmin: false,
    isTenantReadonly: true,
    ...overrides,
  };
}

// Fail-closed par défaut (plan.md action 11.2, correction bloquante 1,
// symétrique au choix fait côté backend get_auth_context()) : un visiteur
// anonyme (pas de token), ou un utilisateur authentifié sans aucun des 3
// rôles RBAC reconnus, est traité côté UI comme le rôle le plus restrictif
// (tenant-readonly, aucun tenant) - purement cosmétique (masque/désactive
// des actions), la vraie sécurité reste le garde serveur ci-dessus.
// `testuser` et le compte de service reçoivent désormais explicitement le
// rôle global-admin côté Keycloak, donc ce choix ne les affecte plus.
export function getAuthInfo(token: string | null): AuthInfo {
  if (!token) return defaultAuthInfo();

  const payload = decodeJwtPayload(token);
  if (!payload) return defaultAuthInfo();

  const roles = ((payload.realm_access as { roles?: string[] } | undefined)?.roles) || [];
  const tenants = (payload.tenants as string[] | undefined) || [];
  const rbacRoles = roles.filter((r) => RBAC_ROLES.includes(r));

  if (rbacRoles.length === 0) {
    return defaultAuthInfo({ roles, tenants });
  }

  const isGlobalAdmin = rbacRoles.includes('global-admin');
  return {
    roles,
    tenants,
    isGlobalAdmin,
    isTenantAdmin: !isGlobalAdmin && rbacRoles.includes('tenant-admin'),
    isTenantReadonly: !isGlobalAdmin && !rbacRoles.includes('tenant-admin') && rbacRoles.includes('tenant-readonly'),
  };
}
