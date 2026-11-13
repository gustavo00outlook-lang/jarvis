"use client";

import { GoogleSidePanel } from "./GoogleSidePanel";
import { OperStatusTicker } from "./OperStatusTicker";

/** Painel Google só com navegação ativa; ticker quando orb docked */
export function OperPanels({
  browserVisible,
  statusVisible,
}: {
  browserVisible: boolean;
  statusVisible: boolean;
}) {
  return (
    <div className="absolute inset-0 z-10 pointer-events-none">
      <GoogleSidePanel visible={browserVisible} />
      <OperStatusTicker visible={statusVisible} />
    </div>
  );
}