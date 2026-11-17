"""What a message Radar sends for the owner may be: its text and the files that travel with it.

On 2026-11-16 the owner approved «send the signed sheet» and what went out was a text written before the sheet
existed, with an unfilled «[ID and IBAN]» in it, a subject line inside the body and no file at all: the notice had
not shown the text, the send could not attach, and nothing checked either. The rules here are checked by code:

- a text with an unfilled field, or one that opens by restating the subject as a header, is never kept as the reply;
- a file that travels with it is named, with its size and folder, in the notice, and is bound to the approval by its
  content hash: a file that changed after the owner said yes is not sent. The owner's credentials never travel.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .jobs.firewall import _SECRET_PATH

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
# A field somebody still has to fill, told by its typography and not by its words, so it holds in any language:
# «[name]», «【金額】», «{{amount}}», «<your phone>», «____», «XXXX». A footnote mark («[1]»), an ellipsis («[...]»), a
# Markdown link («[text](url)») and an address in angle brackets are not. A field written out in words («put the
# IBAN here») is not caught: that is what showing the text in the notice is for.
_PLACEHOLDER = re.compile(
    r"[\[［【](?=[^\]］】\n]*[^\W\d_])[^\[\]［］【】\n]{2,80}[\]］】](?!\()"
    r"|\{\{[^{}\n]{1,80}\}\}"
    r"|<(?!\s)(?![^<>\s]*@)(?!https?:)(?=[^<>\n]*[^\W\d_])[^<>\n/]{3,60}(?<!\s)>"
    r"|_{4,}|\bX{4,}\b"
)
# A label, a colon and then the subject of the thread, as a form would open: «Subject: …», «Asunto: …», «件名：…».
_HEADER = re.compile(r"^\W*[^\W\d_]{1,14}\s?[:：]\s*(?P<rest>.+)", re.DOTALL)


def _norm(text: Any) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").lower()).strip()


def unsendable(text: Any, *, subject: Any = "") -> str:
    """Why this text cannot go out as it is, or "": ``empty``, ``placeholder`` (an unfilled field) or
    ``subject_header`` (the body opens with a label and the subject of the thread, as a form would)."""
    body = str(text or "").strip()
    if not body:
        return "empty"
    if _PLACEHOLDER.search(body):
        return "placeholder"
    stem = _norm(re.sub(r"^\s*((re|rv|fwd?|tr)\s*:\s*)+", "", str(subject or ""), flags=re.IGNORECASE))[:24]
    head = _HEADER.match(body[:300])
    if stem and len(stem) >= 8 and head and _norm(head.group("rest")).startswith(stem):
        return "subject_header"
    return ""


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def attachment_facts(paths: Any) -> list[dict[str, Any]] | None:
    """``[{path, name, size, sha256}]`` for the files a reply carries, or None when any of them cannot go: missing, not
    a regular file, a hidden file, one of the owner's credentials (the files no step of Radar may touch), too large or
    too many. Where a file lives is not a rule: a document another session made is as sendable as one sent in a chat
    (owner's rule, 2026-11-16); what guards it is that the notice names each file and its folder, and that the
    approval is bound to its bytes. One bad file refuses the whole message: a reply that says «attached» with a file
    missing is the failure this guards."""
    wanted = [str(p).strip() for p in (paths or []) if isinstance(p, str) and str(p).strip()]
    if not wanted:
        return []
    if len(wanted) > MAX_ATTACHMENTS:
        return None
    facts: list[dict[str, Any]] = []
    for raw in wanted:
        try:
            path = Path(os.path.expanduser(raw)).resolve(strict=True)  # a link is judged by what it points to
            if not path.is_file() or path.name.startswith(".") or _SECRET_PATH.search(str(path)):
                return None
            size = path.stat().st_size
            if size <= 0 or size > MAX_ATTACHMENT_BYTES:
                return None
            facts.append({"path": str(path), "name": path.name, "size": size, "sha256": _digest(path)})
        except (OSError, ValueError):
            return None
    return facts


def verify_attachments(facts: Any) -> list[str]:
    """The paths to attach, checked again right before the send. Raises ``PermissionError`` when a file is gone or is
    no longer the one the owner approved."""
    paths: list[str] = []
    for fact in facts or []:
        if not isinstance(fact, dict) or not fact.get("path") or not fact.get("sha256"):
            raise PermissionError("attachment without a recorded hash")
        path = Path(str(fact["path"]))
        try:
            same = path.is_file() and not path.is_symlink() and _digest(path) == fact["sha256"]
        except OSError as exc:
            raise PermissionError(f"attachment unreadable: {path.name}") from exc
        if not same:
            raise PermissionError(f"attachment changed since it was approved: {path.name}")
        paths.append(str(path))
    return paths


def human_size(size: Any) -> str:
    try:
        value = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "kB", "MB"):
        if value < 1000 or unit == "MB":
            return f"{value:.0f} {unit}" if unit == "B" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1000
    return ""


def folder_label(path: Any) -> str:
    """The folder of a file as the owner knows it: ``~/informes/gastos``."""
    folder = str(Path(str(path or "")).parent)
    home = str(Path.home())
    return "~" + folder[len(home):] if folder == home or folder.startswith(home + os.sep) else folder
