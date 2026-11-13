/** Detecta pedidos que devem abrir painel browser e mover orb à direita. */
const BROWSER_INTENT_RE =
  /\b(?:abre|abra|abrir|acesse|acesse|acessar|naveg|google|youtube|pesquis|busc|procure|procurar|site|web|internet|calango)\b/i;

export function wantsBrowserPanel(text: string): boolean {
  return BROWSER_INTENT_RE.test((text || "").trim());
}