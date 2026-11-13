// Ponte para o navegador REAL embutido (Tauri). Fora do Tauri, vira no-op
// e o painel continua usando o screenshot (browser comum).

export type Rect = { x: number; y: number; w: number; h: number };

type InvokeFn = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
let invokeFn: InvokeFn | null = null;

function reportNativeError(cmd: string, err: unknown) {
  const msg = err instanceof Error ? err.message : String(err);
  console.error(`[nativeBrowser] ${cmd} falhou:`, msg);
  disableNativeBrowserSession(msg);
  window.dispatchEvent(
    new CustomEvent("jarvis:native-browser-error", { detail: { cmd, message: msg } })
  );
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Navegador nativo embutido (add_child) — ON no app Tauri (screenshot é fallback). */
export function useNativeBrowser(): boolean {
  if (!isTauri()) return false;
  try {
    if (sessionStorage.getItem("jarvis_native_browser_off") === "1") return false;
    const pref = localStorage.getItem("jarvis_native_browser");
    return pref !== "0";
  } catch {
    /* ignore */
  }
  return true;
}

function disableNativeBrowserSession(reason: string) {
  try {
    sessionStorage.setItem("jarvis_native_browser_off", "1");
  } catch {
    /* ignore */
  }
  console.warn(`[nativeBrowser] desativado nesta sessao: ${reason}`);
}

/** Invoke sem a trava de desativação — só exige estar no Tauri. */
async function getInvokeRaw(): Promise<InvokeFn | null> {
  if (!isTauri()) return null;
  if (!invokeFn) {
    try {
      const core = await import("@tauri-apps/api/core");
      invokeFn = core.invoke as unknown as InvokeFn;
    } catch {
      return null;
    }
  }
  return invokeFn;
}

async function getInvoke() {
  if (!useNativeBrowser()) return null;
  if (!invokeFn) {
    try {
      const core = await import("@tauri-apps/api/core");
      invokeFn = core.invoke as unknown as InvokeFn;
    } catch (e) {
      reportNativeError("import", e);
      return null;
    }
  }
  return invokeFn;
}

export async function nativeBrowserShow(url: string, r: Rect): Promise<void> {
  const invoke = await getInvoke();
  if (!invoke) return;
  try {
    await invoke("jarvis_browser_show", { url, x: r.x, y: r.y, w: r.w, h: r.h });
  } catch (e) {
    reportNativeError("jarvis_browser_show", e);
  }
}

export async function nativeBrowserSetBounds(r: Rect): Promise<void> {
  const invoke = await getInvoke();
  if (!invoke) return;
  try {
    await invoke("jarvis_browser_set_bounds", { x: r.x, y: r.y, w: r.w, h: r.h });
  } catch (e) {
    reportNativeError("jarvis_browser_set_bounds", e);
  }
}

export async function nativeBrowserNavigate(url: string): Promise<void> {
  const invoke = await getInvoke();
  if (!invoke) return;
  try {
    await invoke("jarvis_browser_navigate", { url });
  } catch (e) {
    reportNativeError("jarvis_browser_navigate", e);
  }
}

/**
 * Esconder NUNCA pode passar pela trava de desativação: se um erro anterior
 * desligou o modo nativo, a webview já visível ficaria presa na tela como um
 * retângulo preto — fora do DOM, imune a qualquer correção de layout.
 */
export async function nativeBrowserHide(): Promise<void> {
  const invoke = await getInvokeRaw();
  if (!invoke) return;
  try {
    await invoke("jarvis_browser_hide", {});
  } catch (e) {
    // Não usa reportNativeError: re-desativar aqui não ajuda e polui o log
    console.warn("[nativeBrowser] hide falhou:", e instanceof Error ? e.message : e);
  }
}