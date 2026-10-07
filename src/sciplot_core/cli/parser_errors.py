"""Exact CLI parsing with bounded machine feedback and unchanged human help."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, NoReturn


class ArgumentParseError(ValueError):
    reason_code = "cli_invalid_arguments"

    def __init__(self, message: str, *, command: str, issues: list[dict[str, Any]]) -> None:
        super().__init__(message[:512])
        self.repair = {"action": "correct_arguments", "command": command, "issues": issues[:8]}


@dataclass
class _ParseContext:
    json_errors: bool = False
    active: ExactArgumentParser | None = None
    extras: tuple[str, ...] = ()


def _action_name(action: argparse.Action) -> str:
    return "/".join(action.option_strings) or str(action.metavar or action.dest)


def _bounded_choices(values: Any) -> dict[str, Any]:
    choices = list(values)
    result: dict[str, Any] = {"allowed": choices[:32]}
    if len(choices) > 32:
        result["remaining_choice_count"] = len(choices) - 32
    return result


class ExactArgumentParser(argparse.ArgumentParser):
    """Share only error presentation across the parser tree, never inferred flags."""

    def __init__(self, *args: Any, error_context: _ParseContext | None = None,
                 json_errors: bool = False, **kwargs: Any) -> None:
        kwargs["allow_abbrev"] = False
        kwargs["exit_on_error"] = False
        super().__init__(*args, **kwargs)
        self._error_context = error_context or _ParseContext(json_errors=json_errors)
        self._argument_issue: dict[str, Any] | None = None

    def add_subparsers(self, **kwargs: Any) -> Any:
        kwargs.setdefault("parser_class", partial(type(self), error_context=self._error_context))
        return super().add_subparsers(**kwargs)

    def parse_args(self, args: Iterable[str] | None = None, namespace: Any = None) -> Any:
        try:
            return super().parse_args(args, namespace)
        except argparse.ArgumentError as exc:
            self.error(str(exc))

    def parse_known_args(self, args: Iterable[str] | None = None,
                         namespace: Any = None) -> tuple[Any, list[str]]:
        self._error_context.active = self
        self._argument_issue = None
        try:
            parsed, extras = super().parse_known_args(args, namespace)
            self._error_context.extras = tuple(extras)
            return parsed, extras
        except argparse.ArgumentError as exc:
            if exc.argument_name is not None:
                self._argument_issue = self._issue_for_argument(exc)
            self.error(str(exc))

    def _issue_for_argument(self, error: argparse.ArgumentError) -> dict[str, Any]:
        issue: dict[str, Any] = {"argument": error.argument_name, "constraint": "argument"}
        action = next((item for item in self._actions if _action_name(item) == error.argument_name), None)
        if action is None:
            return issue
        if action.choices is not None:
            issue.update(constraint="choice", **_bounded_choices(action.choices))
        elif str(error.message).startswith("expected "):
            issue["constraint"] = "value_required"
        elif str(error.message).startswith("not allowed with argument "):
            issue["constraint"] = "mutually_exclusive"
            group = next((g for g in self._mutually_exclusive_groups if action in g._group_actions), None)
            if group is not None:
                issue["options"] = [_action_name(item) for item in group._group_actions]
        elif action.type is not None:
            issue.update(constraint="type", expected=getattr(action.type, "__name__", str(action.type)))
        return issue

    def _issues_for_message(self, message: str) -> list[dict[str, Any]]:
        if self._argument_issue is not None:
            return [self._argument_issue]
        prefix = "the following arguments are required: "
        if message.startswith(prefix):
            return [{"constraint": "required", "missing": message[len(prefix):].split(", ")[:16]}]
        for group in self._mutually_exclusive_groups:
            options = [_action_name(action) for action in group._group_actions]
            if message == "one of the arguments " + " ".join(options) + " is required":
                return [{"constraint": "one_of_required", "options": options}]
        if message.startswith("unrecognized arguments: "):
            active = self._error_context.active or self
            return [{"constraint": "unrecognized_arguments",
                     "unsupported_options": [value[:128] for value in self._error_context.extras
                                             if value.startswith("-")][:8],
                     "allowed_options": [option for action in active._actions
                                         for option in action.option_strings][:32]}]
        return [{"constraint": "arguments", "message": message[:512]}]

    def error(self, message: str) -> NoReturn:
        if self._error_context.json_errors:
            active = self._error_context.active or self
            raise ArgumentParseError(message, command=active.prog, issues=self._issues_for_message(message))
        super().error(message)


def requests_json(argv: Sequence[str]) -> bool:
    """A literal value after -- is not an output-mode request."""
    options = list(argv)
    return "--json" in options[:options.index("--")] if "--" in options else "--json" in options
