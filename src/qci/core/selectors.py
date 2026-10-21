"""Select a stored run or snapshot without pasting its ID (ADR 0009, section 5).

``SELECTOR := ID | PREFIX | [BACKEND ":"] "latest" ["~" N]``

Resolution is a pure function over ``(id, backend, sort_key)`` entries that the repositories
already list: no SQL and no provider import. Ambiguity is reported with the candidates, never
guessed. Selectors are never stored.
"""

import re
from collections.abc import Sequence
from typing import Literal

from qci.core.errors import QCIError

Kind = Literal["run", "snapshot"]
Entry = tuple[str, str | None, str | None]
"""``(id, backend name, sort key)``. Runs: the run ID. Snapshots: ``calibrated_at`` as a
fixed-width UTC string, or None when the provider gave no date."""

ID_LENGTH = 26
MIN_PREFIX = 8
TIME_PART = 10
"""The first 10 characters of a ULID encode its millisecond."""
MAX_LISTED = 10

_LATEST = re.compile(r"(?:(?P<backend>[^:~]+):)?latest(?:~(?P<n>[^~:]*))?")
_POSITIVE = re.compile(r"[1-9][0-9]*")


class SelectorUsageError(QCIError):
    """The selector fits no form. A usage error: exit 2."""


class SelectorNotFoundError(QCIError):
    """Nothing matches the selector. Exit 1."""


class SelectorAmbiguousError(QCIError):
    """More than one entry fits the selector; nothing was selected. Exit 1."""


def _listed(entries: Sequence[Entry]) -> str:
    shown = [f"  {i}  {backend or '-'}" for i, backend, _ in entries[:MAX_LISTED]]
    if len(entries) > MAX_LISTED:
        shown.append(f"  and {len(entries) - MAX_LISTED} more")
    return "\n".join(shown)


def _latest(
    selector: str, backend: str | None, n: int, entries: Sequence[Entry], kind: Kind
) -> str:
    kept = [e for e in entries if backend is None or e[1] == backend]
    if kind == "snapshot":
        kept = [e for e in kept if e[2] is not None]
        # calibrated_at descending; equal stamps are reported below, never ordered by guess.
        ordered = sorted(kept, key=lambda e: (e[2] or "", e[0]), reverse=True)

        def same(a: Entry, b: Entry) -> bool:
            return a[2] == b[2]

        reason = "share their calibrated_at, so their order is not known"
    else:
        ordered = sorted(kept, key=lambda e: e[0], reverse=True)

        def same(a: Entry, b: Entry) -> bool:
            return a[0][:TIME_PART] == b[0][:TIME_PART]

        reason = "were created in the same millisecond, so their order is not known"
    if n >= len(ordered):
        scope = f" on {backend}" if backend else ""
        raise SelectorNotFoundError(
            f"{selector!r} selects nothing: there are {len(ordered)} {kind}s{scope}"
            + (" with a calibrated_at" if kind == "snapshot" else "")
        )
    chosen = ordered[n]
    tied = [e for e in ordered if same(e, chosen)]
    if len(tied) > 1:
        raise SelectorAmbiguousError(
            f"{selector!r} is ambiguous: these {kind}s {reason}:\n{_listed(tied)}"
        )
    return chosen[0]


def resolve(selector: str, entries: Sequence[Entry], kind: Kind) -> str:
    """The ID that ``selector`` names among ``entries``.

    Raises ``SelectorUsageError`` (exit 2), ``SelectorNotFoundError`` or
    ``SelectorAmbiguousError`` (exit 1).
    """
    latest = _LATEST.fullmatch(selector)
    if latest is not None:
        backend, n = latest.group("backend"), latest.group("n")
        if n is not None and not _POSITIVE.fullmatch(n):
            raise SelectorUsageError(
                f"{selector!r}: '~' must be followed by an integer of 1 or more"
            )
        if kind == "snapshot" and backend is None:
            raise SelectorUsageError(
                f"{selector!r}: a snapshot selector names its backend, e.g. ibm_fez:{selector}"
            )
        return _latest(selector, backend, int(n) if n else 0, entries, kind)
    if ":" in selector or "~" in selector:
        raise SelectorUsageError(f"{selector!r} is not an ID, a prefix or [BACKEND:]latest[~N]")
    ids = [e[0] for e in entries]
    if selector in ids:
        return selector
    if len(selector) == ID_LENGTH:
        raise SelectorNotFoundError(f"no {kind} with id {selector!r}")
    if not MIN_PREFIX <= len(selector) < ID_LENGTH:
        raise SelectorUsageError(
            f"{selector!r} is not a {ID_LENGTH}-character ID, and a prefix needs {MIN_PREFIX} to "
            f"{ID_LENGTH - 1} characters"
        )
    matches = [e for e in entries if e[0].startswith(selector)]
    if not matches:
        raise SelectorNotFoundError(f"no {kind} ID starts with {selector!r}")
    if len(matches) > 1:
        raise SelectorAmbiguousError(
            f"prefix {selector!r} matches {len(matches)} {kind}s:\n"
            + _listed(sorted(matches, key=lambda e: e[0], reverse=True))
        )
    return matches[0][0]
