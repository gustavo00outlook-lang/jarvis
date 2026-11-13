import { useJarvis } from "./state";
import { motionCloseDelay, motionReleaseDelay } from "./motion";

const PANEL_TOOLS = new Set([
  "browse_open",
  "open_browser_search",
  "open_url",
  "web_search",
]);

const ACTION_TOOLS = new Set([
  "open_app",
  "open_full_browser",
  "open_url",
  "open_browser_search",
  "web_search",
  "run_command",
  "look_at_screen",
  "watch_screen",
  "desktop_click",
  "desktop_type",
  "desktop_press",
  "desktop_scroll",
  "set_volume",
  "media_control",
  "system_status",
  "current_datetime",
]);

export function toolNames(tools: { tool?: string }[] | undefined): string[] {
  return (tools || []).map((t) => String(t.tool || "").trim()).filter(Boolean);
}

export function usesPanel(tools: { tool?: string }[] | undefined): boolean {
  return toolNames(tools).some(
    (n) => PANEL_TOOLS.has(n) || n.startsWith("browse_"),
  );
}

export function usesPcAction(tools: { tool?: string }[] | undefined): boolean {
  return toolNames(tools).some(
    (n) => ACTION_TOOLS.has(n) || n.startsWith("browse_") || n.startsWith("desktop_"),
  );
}

export function closedBrowser(tools: { tool?: string }[] | undefined): boolean {
  return toolNames(tools).includes("browse_close");
}

/** Sincroniza orb dock + painel com as tools que o backend executou */
export function applyChatToolsToUi(tools: { tool?: string }[] | undefined): {
  panelClosing: boolean;
  keepWorking: boolean;
} {
  if (closedBrowser(tools)) {
    useJarvis.getState().setBrowserActive(false);
    window.dispatchEvent(new CustomEvent("jarvis:browser-clear"));
    return { panelClosing: true, keepWorking: false };
  }

  const panel = usesPanel(tools);
  const action = usesPcAction(tools);

  if (panel) {
    useJarvis.getState().setBrowserActive(true);
  }
  if (action && !panel) {
    useJarvis.getState().setWorking(true);
  }

  if (toolNames(tools).includes("media_control")) {
    useJarvis.getState().setShowMusicWidget(true);
    useJarvis.getState().playMusic();
  }

  return { panelClosing: false, keepWorking: action || panel };
}

export function scheduleReleaseWorking(opts: {
  panelClosing: boolean;
  keepWorking: boolean;
  hasPanel: boolean;
}) {
  const release = () => {
    if (!useJarvis.getState().browserActive) {
      useJarvis.getState().setWorking(false);
    }
  };
  if (opts.panelClosing) {
    setTimeout(release, motionCloseDelay());
    return;
  }
  if (opts.hasPanel) return;
  if (opts.keepWorking) {
    setTimeout(release, motionReleaseDelay() + 140);
    return;
  }
  setTimeout(release, motionReleaseDelay());
}