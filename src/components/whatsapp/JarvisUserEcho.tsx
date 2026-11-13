"use client";

/** Dispara quando o usuário envia (Enter) ou fala */
export function dispatchUserUtterance(text: string, interim = false) {
  const t = text.trim();
  if (!t) return;
  window.dispatchEvent(
    new CustomEvent("jarvis:user-utterance", { detail: { text: t, interim } })
  );
}

export function dispatchUserSent(text: string) {
  const t = text.trim();
  if (!t) return;
  window.dispatchEvent(new CustomEvent("jarvis:user-sent", { detail: { text: t } }));
}