import { isTauri } from "./nativeBrowser";

/** App Tauri desktop vs browser em :3000 */
export function isJarvisApp(): boolean {
  return isTauri();
}

/** Toda navegação/pesquisa abre o painel embutido — nunca Chrome externo */
export function preferPanelSearch(): boolean {
  return true;
}