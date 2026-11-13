"""
Fase 2 → Legacy Actions Adapter

Converts the beautiful typed ActionPlan (from xAI Structured Outputs)
into the simple dict format that the old `actions.execute(action, params)` expects.

This is the glue that makes the reliable new structured path actually control the PC.
"""

from typing import Dict, Any, Tuple, List
from action_schema import ActionPlan, Action


def _single_to_legacy(action: Action) -> Tuple[str, Dict[str, Any]]:
    """Map one typed Action to legacy (name, params)."""
    action_type = getattr(action, "action", "none")

    if action_type == "none":
        return "none", {}

    if action_type == "open_app":
        return "open_app", {
            "name": action.app_name,
            "arguments": getattr(action, "arguments", None)
        }

    if action_type == "close_app":
        return "close_app", {"name": action.app_name}

    if action_type == "volume":
        if action.direction == "set" and action.value is not None:
            return "set_volume", {"level": action.value}
        elif action.direction in ("up", "down"):
            delta = 10 if action.direction == "up" else -10
            return "set_volume", {"change": str(delta)}
        elif action.direction == "mute":
            return "set_volume", {"mute": True}
        elif action.direction == "unmute":
            return "set_volume", {"unmute": True}
        return "set_volume", {}

    if action_type == "media_control":
        return "media_control", {"command": action.command}

    if action_type == "search_web":
        return "search_web", {"query": action.query}

    if action_type == "search_x":
        return "search_web", {"query": f"site:x.com {action.query}"}

    if action_type == "run_command":
        return "run_command", {"command": action.command}

    if action_type == "write_note":
        return "write_note", {"title": action.title, "content": action.content}

    if action_type == "remember":
        return "remember", {"key": action.key, "value": action.value}

    if action_type == "forget":
        return "forget", {"key": action.key}

    if action_type == "show_status":
        return "show_status", {}

    if action_type == "open_browser_search":
        return "open_browser_search", {
            "query": action.query,
            "browser": getattr(action, "browser", "chrome")
        }

    return "none", {}


def action_plan_to_legacy(plan: ActionPlan) -> Tuple[str, Dict[str, Any]]:
    """
    Legacy single for compat (first action). Prefer action_plan_to_legacy_list for compounds.
    """
    acts = getattr(plan, 'actions', None) or ([plan.action] if hasattr(plan, 'action') and plan.action else [])
    if not acts:
        return "none", {}
    return _single_to_legacy(acts[0])


def action_plan_to_legacy_list(plan: ActionPlan) -> List[Tuple[str, Dict[str, Any]]]:
    """Returns list of (action_name, params) for sequential execution of compound commands."""
    acts = getattr(plan, 'get_actions', lambda: plan.actions)()
    if not acts:
        # compat for old single
        if hasattr(plan, 'action') and plan.action:
            return [_single_to_legacy(plan.action)]
        return [("none", {})]
    return [_single_to_legacy(a) for a in acts]


def execute_structured_action(plan: ActionPlan, actions_module) -> str:
    """
    High level helper: takes a validated ActionPlan and executes actions sequentially (supports compound lists).
    Returns joined feedback string from all steps.
    """
    steps = action_plan_to_legacy_list(plan)
    if not steps or (len(steps) == 1 and steps[0][0] == "none"):
        return "Nenhuma ação executada."

    feedbacks = []
    for i, (action_name, params) in enumerate(steps, 1):
        if action_name == "none":
            feedbacks.append(f"[step {i}] Nenhuma ação.")
            continue
        try:
            fb = actions_module.execute(action_name, params)
            feedbacks.append(f"[step {i}] {action_name}: {fb or 'ok'}")
        except Exception as e:
            feedbacks.append(f"[step {i}] Erro em {action_name}: {e}")
    return " | ".join(feedbacks)


def is_action_risky(plan: ActionPlan) -> bool:
    """Central place to decide if we should ask for confirmation before executing."""
    return plan.requires_confirmation()