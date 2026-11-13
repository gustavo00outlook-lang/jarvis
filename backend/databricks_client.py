"""
Cliente híbrido Databricks — consultas SQL no lakehouse via Statement Execution API.

Variáveis de ambiente:
  DATABRICKS_HOST          — ex: https://adb-xxx.azuredatabricks.net
  DATABRICKS_TOKEN         — PAT ou OAuth token
  DATABRICKS_WAREHOUSE_ID  — SQL warehouse ID (obrigatório para SQL)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_POLL_INTERVAL = 0.8
_POLL_TIMEOUT = 90.0


def is_configured() -> bool:
    return bool(_host() and _token() and _warehouse_id())


def _host() -> str:
    return (os.getenv("DATABRICKS_HOST") or "").strip().rstrip("/")


def _token() -> str:
    return (os.getenv("DATABRICKS_TOKEN") or "").strip()


def _warehouse_id() -> str:
    return (os.getenv("DATABRICKS_WAREHOUSE_ID") or "").strip()


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    host = _host()
    token = _token()
    if not host or not token:
        raise RuntimeError("Databricks não configurado (DATABRICKS_HOST / DATABRICKS_TOKEN).")

    url = f"{host}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Databricks HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Databricks indisponível: {e.reason}") from e


def _wait_statement(statement_id: str) -> Dict[str, Any]:
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        status = _request("GET", f"/api/2.0/sql/statements/{statement_id}")
        state = (status.get("status") or {}).get("state", "")
        if state in ("SUCCEEDED", "FAILED", "CANCELED"):
            return status
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError("Timeout aguardando resultado Databricks.")


def _format_result(payload: Dict[str, Any]) -> str:
    status = payload.get("status") or {}
    state = status.get("state", "UNKNOWN")
    if state == "FAILED":
        err = status.get("error") or {}
        return f"Consulta falhou: {err.get('message') or err}"

    manifest = payload.get("manifest") or {}
    schema = manifest.get("schema") or {}
    columns = [c.get("name", f"col{i}") for i, c in enumerate(schema.get("columns") or [])]
    rows: List[List[Any]] = (payload.get("result") or {}).get("data_array") or []

    if not rows:
        return "Consulta concluída — nenhuma linha retornada."

    lines = [" | ".join(columns)]
    lines.append("-" * min(80, len(lines[0])))
    for row in rows[:50]:
        lines.append(" | ".join(str(v) if v is not None else "" for v in row))
    if len(rows) > 50:
        lines.append(f"... (+{len(rows) - 50} linhas)")
    return "\n".join(lines)


def run_query(sql: str, catalog: Optional[str] = None, schema: Optional[str] = None) -> str:
    """Executa SELECT no SQL warehouse e retorna tabela em texto."""
    statement = (sql or "").strip()
    if not statement:
        return "SQL vazio — informe uma consulta SELECT."

    low = statement.lower()
    if not low.startswith("select") and not low.startswith("with"):
        return "Por segurança, só aceito consultas SELECT (ou WITH ... SELECT)."

    if not is_configured():
        return (
            "Conector Databricks inativo. Configure DATABRICKS_HOST, DATABRICKS_TOKEN "
            "e DATABRICKS_WAREHOUSE_ID no ambiente do backend."
        )

    body: Dict[str, Any] = {
        "warehouse_id": _warehouse_id(),
        "statement": statement,
        "wait_timeout": "0s",
        "on_wait_timeout": "CONTINUE",
    }
    if catalog:
        body["catalog"] = catalog
    if schema:
        body["schema"] = schema

    started = _request("POST", "/api/2.0/sql/statements", body)
    stmt_id = started.get("statement_id")
    if not stmt_id:
        return f"Resposta inesperada Databricks: {json.dumps(started)[:300]}"

    final = _wait_statement(stmt_id)
    return _format_result(final)