# -*- coding: utf-8 -*-
"""
BaseModule — the "Everything-is-a-Module" contract (V3 vertical axis).

Every vertical capability (M1..M8) is packaged as a standalone :class:`BaseModule`
subclass that:

  * runs independently via a Python API (:meth:`run`) and a CLI subcommand
    (:meth:`register_cli` + :meth:`from_cli_args`);
  * returns a uniform :class:`ModuleResult` (never raises across the boundary
    when invoked through :meth:`safe_run`);
  * can be *composed* by the orchestrator without any module knowing about the
    others.

This module is intentionally dependency-light (stdlib only) so that every
capability package can import it without pulling heavy optional deps.

Contract stability
------------------
This file is a **shared foundation contract**. Concrete capability modules
(``ai/modules/*.py``, ``ai/requirements/module.py``, ...) *import* from here but
must **not** modify it. Changes to this file are owned by the integration owner.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


# ── Uniform result envelope ────────────────────────────────────────────

@dataclass
class ModuleResult:
    """Uniform return value for every module invocation.

    Fields:
        ok:        True on success, False on handled failure.
        data:      Structured payload (JSON-serializable) produced by the module.
        message:   Human-readable summary or error message.
        artifacts: Paths to any files produced (reports, plots, caches).
        module:    Name of the module that produced this result.
    """
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    artifacts: list[str] = field(default_factory=list)
    module: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "module": self.module,
            "message": self.message,
            "data": self.data,
            "artifacts": list(self.artifacts),
        }

    @classmethod
    def fail(cls, message: str, module: str = "", **data: Any) -> "ModuleResult":
        return cls(ok=False, message=message, module=module, data=dict(data))

    @classmethod
    def success(
        cls,
        message: str = "",
        module: str = "",
        artifacts: Optional[list[str]] = None,
        **data: Any,
    ) -> "ModuleResult":
        return cls(
            ok=True,
            message=message,
            module=module,
            artifacts=list(artifacts or []),
            data=dict(data),
        )


# ── Base module ────────────────────────────────────────────────────────

class BaseModule(abc.ABC):
    """Abstract base for a standalone, composable capability module.

    Subclasses set the class attributes :attr:`name` and :attr:`description`
    and implement :meth:`run`. CLI wiring is optional; override
    :meth:`register_cli` / :meth:`from_cli_args` to expose a subcommand.

    Example
    -------
    >>> class Echo(BaseModule):
    ...     name = "echo"
    ...     description = "echo back the input"
    ...     def run(self, *, text: str = "", **_: object) -> ModuleResult:
    ...         return ModuleResult.success(message=text, module=self.name, echoed=text)
    >>> Echo().safe_run(text="hi").data["echoed"]
    'hi'
    """

    #: CLI-friendly identifier, e.g. ``"code-structure"``. Override in subclass.
    name: str = "base"
    #: One-line human description shown in CLI help. Override in subclass.
    description: str = ""

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> ModuleResult:
        """Execute the module. Implementations may raise; callers that need
        graceful degradation should use :meth:`safe_run` instead."""
        raise NotImplementedError

    def safe_run(self, **kwargs: Any) -> ModuleResult:
        """Run the module, converting any unexpected exception into a failed
        :class:`ModuleResult`. Never raises across the module boundary.

        This is the entry point the orchestrator/Agent loop should use so that
        one module crashing cannot abort the whole pipeline.
        """
        try:
            result = self.run(**kwargs)
            if not isinstance(result, ModuleResult):  # defensive contract check
                return ModuleResult.fail(
                    f"{self.name}.run() returned {type(result).__name__}, "
                    f"expected ModuleResult",
                    module=self.name,
                )
            result.module = result.module or self.name
            return result
        except Exception as exc:  # noqa: BLE001 - boundary guard by design
            log.exception("Module '%s' failed", self.name)
            return ModuleResult.fail(f"{type(exc).__name__}: {exc}", module=self.name)

    # ── Optional CLI hooks (override to expose a subcommand) ────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        """Register a subparser for this module and return it.

        Default implementation creates a subcommand named :attr:`name` with the
        module description. Subclasses should add their own arguments and set the
        handler, e.g.::

            p = super().register_cli(subparsers)
            p.add_argument("--query", required=True)
            p.set_defaults(_module_cls=cls)
            return p
        """
        parser = subparsers.add_parser(cls.name, help=cls.description or cls.name)
        parser.set_defaults(_module_cls=cls)
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "BaseModule":
        """Construct a module instance from parsed CLI args. Override if the
        constructor needs configuration (router, config, paths)."""
        return cls()
