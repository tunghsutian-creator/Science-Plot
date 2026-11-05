"""Finite admission for the existing local-timing metadata module, without executing it."""
from __future__ import annotations

import ast
from pathlib import Path


TASK_TIMING_PATH = "src/sciplot_core/task_timing.py"
_IMPORTS = {
    "__future__": ("annotations",), "contextvars": ("ContextVar",),
    "functools": ("wraps",), "pathlib": ("Path",), "time": ("perf_counter",),
    "typing": ("Any", "Callable", "ParamSpec"),
}
_FIELDS = {"scope", "calls", "total_seconds", "last_call_seconds",
           "last_call_phases_seconds", "external_model_seconds"}


def _same(node: ast.AST | None, expression: str) -> bool:
    return node is not None and ast.unparse(node) == ast.unparse(ast.parse(expression, mode="eval").body)


def _function_boundary(function: ast.FunctionDef) -> bool:
    """Only the current module's metadata bindings and scalar arithmetic may vary."""
    bindings = {
        "clock": "_ACTIVE.get()", "now": "perf_counter()",
        "totals": 'clock["phases"]', "started": "perf_counter()",
        "token": '_ACTIVE.set({"started": started, "last": started, "phases": {}})',
    }
    calls = {
        "observe_phase": {"_ACTIVE.get", "perf_counter", "str", "clock.get", "clock.update", "totals.get"},
        "finish_timing": {"_ACTIVE.get", "observe_phase", "Path", "perf_counter", "state.get",
                          "previous.get", "round", "clock['phases'].items"},
        "timed_task_call": {"perf_counter", "_ACTIVE.set", "_ACTIVE.reset", "wraps", "function"},
    }[function.name]
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef,
                             ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom,
                             ast.Lambda, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor,
                             ast.While, ast.Delete, ast.AugAssign, ast.NamedExpr, ast.Raise)):
            return False
        if isinstance(node, ast.FunctionDef) and node is not function and not (
                function.name == "timed_task_call" and node.name == "run"):
            return False
        if isinstance(node, ast.Try) and function.name != "timed_task_call":
            return False
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return False
        if isinstance(node, ast.Call):
            called = ast.unparse(node.func)
            if called not in calls:
                return False
            if called == "clock.update" and not _same(node, 'clock.update(root=str(root), phase=state["phase"], last=now)'):
                return False
            if called == "_ACTIVE.reset" and not _same(node, "_ACTIVE.reset(token)"):
                return False
            if called == "_ACTIVE.get" and not _same(node, "_ACTIVE.get()"):
                return False
            if called == "_ACTIVE.set" and not _same(node, bindings["token"]):
                return False
            if called == "observe_phase" and not _same(node, 'observe_phase(Path(state["task_dir"]), state)'):
                return False
            if called == "Path" and not _same(node, 'Path(state["task_dir"])'):
                return False
            if called == "state.get" and not _same(node, 'state.get("local_timing", {})'):
                return False
            if called == "clock.get" and not any(_same(node, value) for value in (
                    'clock.get("root")', 'clock.get("phase", "setup")')):
                return False
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                return False
            target, value = node.targets[0], node.value
            if isinstance(target, ast.Name):
                if target.id in bindings:
                    if not _same(value, bindings[target.id]):
                        return False
                elif target.id == "previous":
                    expected = 'clock.get("phase", "setup")' if function.name == "observe_phase" else 'state.get("local_timing", {})'
                    if not _same(value, expected):
                        return False
                elif target.id != "elapsed" or function.name != "finish_timing":
                    return False
            elif _same(target, 'state["local_timing"]'):
                if (function.name != "finish_timing" or not isinstance(value, ast.Dict)
                        or {key.value for key in value.keys if isinstance(key, ast.Constant)} != _FIELDS
                        or len(value.keys) != len(_FIELDS)):
                    return False
            elif not (function.name == "observe_phase" and _same(target, "totals[previous]")):
                return False
        if isinstance(node, ast.comprehension) and not (
                _same(node.target, "(key, value)") and _same(node.iter, 'clock["phases"].items()')
                and not node.ifs and not node.is_async):
            return False
    return True


def task_timing_feedback_eligible(repo_root: Path) -> bool:
    """Admit only this current metadata boundary; callers own Git scope and execution facts.

    Unknown source is never imported or executed to decide whether it is safe.
    The local contract test exercises the admitted implementation's behavior.
    """
    path = repo_root / TASK_TIMING_PATH
    try:
        if path.is_symlink():
            return False
        module = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return False
    imports, functions, globals_ = {}, {}, {}
    for node in module.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.ImportFrom) and not node.level and all(item.asname is None for item in node.names):
            if node.module in imports:
                return False
            imports[node.module] = tuple(item.name for item in node.names)
        elif isinstance(node, ast.FunctionDef) and node.name not in functions:
            functions[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else node.target if isinstance(node, ast.AnnAssign) else None
            if not isinstance(target, ast.Name) or target.id in globals_ or node.value is None:
                return False
            globals_[target.id] = node.value
        else:
            return False
    if (imports != _IMPORTS or set(functions) != {"observe_phase", "finish_timing", "timed_task_call"}
            or set(globals_) != {"_P", "_ACTIVE"}
            or not _same(globals_["_P"], 'ParamSpec("_P")')
            or not _same(globals_["_ACTIVE"], 'ContextVar("sciplot_task_clock", default=None)')):
        return False
    for name, arguments in (("observe_phase", ["root", "state"]), ("finish_timing", ["state"]),
                            ("timed_task_call", ["function"])):
        function = functions[name]
        if ([arg.arg for arg in function.args.args] != arguments or function.args.posonlyargs
                or function.args.kwonlyargs or function.args.defaults or function.args.vararg
                or function.args.kwarg or function.decorator_list or not _function_boundary(function)):
            return False
    wrapper = functions["timed_task_call"]
    if (len(wrapper.body) != 2 or not isinstance(wrapper.body[0], ast.FunctionDef)
            or not isinstance(wrapper.body[1], ast.Return) or not _same(wrapper.body[1].value, "run")):
        return False
    run = wrapper.body[0]
    return (run.name == "run" and not run.args.args and not run.args.posonlyargs and not run.args.kwonlyargs
            and run.args.vararg is not None and run.args.vararg.arg == "args"
            and run.args.kwarg is not None and run.args.kwarg.arg == "kwargs"
            and not run.args.defaults and not run.args.kw_defaults
            and len(run.decorator_list) == 1 and _same(run.decorator_list[0], "wraps(function)")
            and len(run.body) == 3 and isinstance(run.body[2], ast.Try)
            # Their exact RHS bindings were checked by _function_boundary.
            # A compound first statement could otherwise invoke the callback too.
            and isinstance(run.body[0], ast.Assign) and len(run.body[0].targets) == 1
            and _same(run.body[0].targets[0], "started")
            and isinstance(run.body[1], ast.Assign) and len(run.body[1].targets) == 1
            and _same(run.body[1].targets[0], "token")
            and len(run.body[2].body) == 1 and isinstance(run.body[2].body[0], ast.Return)
            and _same(run.body[2].body[0].value, "function(*args, **kwargs)")
            and not run.body[2].handlers and not run.body[2].orelse
            and len(run.body[2].finalbody) == 1 and isinstance(run.body[2].finalbody[0], ast.Expr)
            and _same(run.body[2].finalbody[0].value, "_ACTIVE.reset(token)"))
