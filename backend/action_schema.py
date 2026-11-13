"""
Action Schema - Fase 2: Structured Outputs for JARVIS

This defines the canonical, type-safe actions that the JARVIS orb can reliably execute
on the user's PC. 

We use Pydantic + xAI Responses API structured outputs so the model cannot hallucinate
invalid action names or parameter shapes.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal, Optional, Union, List, Annotated, Any, Dict
from enum import Enum


class ActionType(str, Enum):
    """All actions the agent is allowed to perform."""
    NONE = "none"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    VOLUME = "volume"
    MEDIA_CONTROL = "media_control"
    SEARCH_WEB = "search_web"
    SEARCH_X = "search_x"
    RUN_COMMAND = "run_command"
    WRITE_NOTE = "write_note"
    REMEMBER = "remember"
    FORGET = "forget"
    SHOW_STATUS = "show_status"
    OPEN_BROWSER_SEARCH = "open_browser_search"


class VolumeAction(BaseModel):
    action: Literal["volume"]
    direction: Literal["up", "down", "mute", "unmute", "set"] = Field(..., description="What to do with volume")
    value: Optional[int] = Field(None, ge=0, le=100, description="Target volume 0-100 when direction=set")


class MediaControlAction(BaseModel):
    action: Literal["media_control"]
    command: Literal["play_pause", "next", "previous", "stop"]


class OpenAppAction(BaseModel):
    action: Literal["open_app"]
    app_name: str = Field(..., min_length=1, description="Name of the application to open (e.g. 'chrome', 'vscode', 'spotify')")
    arguments: Optional[str] = Field(None, description="Optional command line arguments")


class CloseAppAction(BaseModel):
    action: Literal["close_app"]
    app_name: str


class SearchWebAction(BaseModel):
    action: Literal["search_web"]
    query: str
    summarize: bool = True


class SearchXAction(BaseModel):
    action: Literal["search_x"]
    query: str
    latest: bool = True


class OpenBrowserSearchAction(BaseModel):
    action: Literal["open_browser_search"]
    query: str = Field(..., description="Search query to open in browser (e.g. 'xai' or 'what is grok')")
    browser: str = Field("chrome", description="Browser to use: chrome, edge, firefox etc. Defaults to chrome for google.com search")


class RunCommandAction(BaseModel):
    action: Literal["run_command"]
    command: str = Field(..., description="Safe shell command to execute")
    confirm: bool = Field(False, description="Whether this needs explicit user confirmation")


class WriteNoteAction(BaseModel):
    action: Literal["write_note"]
    title: str
    content: str


class RememberAction(BaseModel):
    action: Literal["remember"]
    key: str
    value: str


class ForgetAction(BaseModel):
    action: Literal["forget"]
    key: str


class ShowStatusAction(BaseModel):
    action: Literal["show_status"]


class NoAction(BaseModel):
    action: Literal["none"] = "none"
    reason: Optional[str] = None


# Union of all possible actions the model can return
# IMPORTANT: Annotated + discriminator so xAI structured outputs / .parse() works reliably
Action = Annotated[
    Union[
        VolumeAction,
        MediaControlAction,
        OpenAppAction,
        CloseAppAction,
        SearchWebAction,
        SearchXAction,
        RunCommandAction,
        WriteNoteAction,
        RememberAction,
        ForgetAction,
        ShowStatusAction,
        OpenBrowserSearchAction,
        NoAction,
    ],
    Field(discriminator="action"),
]


class ActionPlan(BaseModel):
    """
    The root structured output we force the model to return.
    
    This is what we will use with xAI structured outputs / .parse().
    Updated for compound commands: 'actions' is a list to support sequential multi-step
    like "open google and search for xai, then open notepad and type hello".
    Hermes/xAI will break complex into ordered list instead of returning "none".
    """
    model_config = ConfigDict(
        use_attribute_docstrings=True,
        # Helps xAI structured outputs produce cleaner JSON matching the schema
    )

    thought: str = Field(..., description="Brief reasoning about what the user wants, including if compound steps detected")
    actions: List[Action] = Field(..., min_length=1, description="List of concrete actions to execute sequentially. For single-step use a 1-item list. Enables reliable compound/sequential handling.")
    speak: str = Field(..., description="What JARVIS should say to the user (natural, in character). Mention steps if compound.")
    confidence: float = Field(0.8, ge=0, le=1, description="How confident the model is this is the right action")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_single_action(cls, data: Any) -> Any:
        """Support old pending data and single 'action' for smooth transition + compound."""
        if isinstance(data, dict):
            if "actions" not in data and "action" in data:
                single = data.get("action")
                data = dict(data)  # copy
                data["actions"] = [single] if single else [{"action": "none"}]
            if data.get("actions") in (None, [], [None]):
                data["actions"] = [{"action": "none", "reason": "normalized"}]
        return data

    def requires_confirmation(self) -> bool:
        """Returns True for actions that can be destructive or have side effects. Checks any in the sequence."""
        risky_types = {"run_command", "close_app", "forget", "write_note"}
        for a in self.actions:
            if getattr(a, "action", None) in risky_types:
                return True
            # volume set to 0 or mute is risky
            if getattr(a, "action", None) == "volume":
                v = getattr(a, "value", None)
                if v is not None and (v <= 0 or getattr(a, "direction", "") == "mute"):
                    return True
            # aggressive media stop
            if getattr(a, "action", None) == "media_control" and getattr(a, "command", "") == "stop":
                return True
            if getattr(a, "action", None) == "run_command" and getattr(a, "confirm", False):
                return True
        return False

    def get_actions(self) -> List[Action]:
        """Helper to get the sequence (always list)."""
        return self.actions or []


# Example usage in code:
#
# from openai import OpenAI
# client = OpenAI(base_url="https://api.x.ai/v1", api_key=...)
#
# completion = client.beta.chat.completions.parse(
#     model="grok-4.3",
#     messages=[...],
#     response_format=ActionPlan,
# )
# plan: ActionPlan = completion.choices[0].message.parsed
