"""Attention preferences: scoped, versioned, append-only rules the owner teaches the plugin.

Ported from mail-intelligence. A preference never executes anything: it only raises or lowers
how loudly a signal is surfaced (silent, digest, notify, prefer).
"""
from __future__ import annotations

from typing import Any

FIELDS = frozenset({"id", "dimension", "scope", "effect", "exceptions", "instruction", "origin", "status"})
DIMENSIONS = frozenset({"notification", "investigation", "response"})
EFFECTS = frozenset({"silent", "digest", "notify", "prefer"})
ORIGINS = frozenset({"explicit", "inferred", "imported"})
STATUSES = frozenset({"active", "candidate", "disabled"})
SCOPE_FIELDS = ("account", "sender", "sender_name", "message_type", "project", "kind", "source_kind", "repo", "subject_stem")
# Who writes, not from where: a display name is chosen by whoever writes the mail, so only a rule that stays quiet can
# trust one. A name scoped notify or prefer would let anyone raise their own mail by writing that name, so it needs the
# address beside it; silent and digest can stand on the name alone.
NAME_ONLY_EFFECTS = frozenset({"silent", "digest"})


def sender_address(sender: Any) -> str:
    """The bare email address of a sender, lowercased: «Octopus Energy <hola@octopusenergy.example>» → «hola@octopusenergy.example».
    Preferences are scoped by address (that is what the owner means by "this sender"), so matching normalises the
    signal's sender the same way before comparing."""
    import re

    text = str(sender or "")
    match = re.search(r"<([^>]+)>", text)
    return (match.group(1) if match else text).strip().lower()


def _decoded(value: str) -> str:
    """An RFC 2047 name («=?UTF-8?Q?Notificaci=C3=B3n?=») as the text it stands for. A mail leaves the header encoded
    and not every source decodes it, so a name only matches when both sides are decoded before comparing. A header that
    cannot be decoded is compared as it came."""
    import email.header

    if "=?" not in value:
        return value
    try:
        parts = email.header.decode_header(value)
    except Exception:  # noqa: BLE001 — a broken header is data, not a failure worth raising
        return value
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            text = text.decode(charset or "utf-8", "replace")
        out.append(text)
    return "".join(out)


def sender_name(sender: Any) -> str:
    """The display name of a sender, lowercased and unquoted: «"coderabbitai[bot]" <notifications@github.com>» →
    «coderabbitai[bot]». GitHub relays every App from its own address and keeps the bot's name in the display name, so
    that name is the only thing that tells one bot from another. Returns "" when the sender carries no name, which
    names nobody and therefore matches nothing."""
    import re

    text = _decoded(str(sender or "")).strip()
    match = re.match(r'^\s*"(?P<name>.*?)"\s*<', text) or re.match(r"^\s*(?P<name>[^<]*?)\s*<", text)
    name = match.group("name") if match else ("" if "@" in text else text)
    return " ".join(name.strip().strip('"').split()).lower()


def subject_stem(subject: Any) -> str:
    """The part of a subject that repeats across a family of messages: lowercase, without list tags,
    numbers, dates or reply prefixes, first five words. «[newsroom-org] A security advisory on markdown-it
    affects…» and «Security alert» each become a stem a mute can hang on."""
    import re

    text = str(subject or "").lower()
    text = re.sub(r"^\s*((re|fwd?|fw|rv|aw|sv)\s*:\s*)+", "", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[#\d][\w./-]*", " ", text)
    words = [w for w in re.split(r"[^\wáéíóúüñ]+", text) if w]
    return " ".join(words[:5])


def validate_preference(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("preference fields must match the schema")
    for key in ("id", "instruction"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    for key, allowed in (("dimension", DIMENSIONS), ("effect", EFFECTS), ("origin", ORIGINS), ("status", STATUSES)):
        if not isinstance(data[key], str) or data[key] not in allowed:
            raise ValueError(f"invalid {key}")
    scope = data["scope"]
    if not isinstance(scope, dict) or set(scope) - set(SCOPE_FIELDS):
        raise ValueError("invalid scope")
    if any(not isinstance(v, str) or not v.strip() for v in scope.values()):
        raise ValueError("scope values must be non-empty strings")
    if names_only_scope(scope, data["effect"]):
        raise ValueError("sender_name without sender is only for silent or digest")
    if not isinstance(data["exceptions"], list) or any(
        not isinstance(v, str) or not v.strip() for v in data["exceptions"]
    ):
        raise ValueError("exceptions must be a list of strings")
    return data


def new_preference(
    preference_id: str, *, instruction: str, dimension: str = "notification", scope: dict[str, str] | None = None,
    effect: str = "silent", exceptions: tuple[str, ...] = (), origin: str = "explicit", status: str = "active",
) -> dict[str, Any]:
    return validate_preference(
        {
            "id": preference_id, "dimension": dimension, "scope": dict(scope or {}), "effect": effect,
            "exceptions": list(exceptions), "instruction": instruction, "origin": origin, "status": status,
        }
    )


def valid_scope(scope: Any) -> bool:
    """A scope Radar can judge: only known fields, each a non-empty string."""
    return (isinstance(scope, dict) and not (set(scope) - set(SCOPE_FIELDS))
            and all(isinstance(v, str) and v.strip() for v in scope.values()))


def scope_matches(scope: dict[str, Any], observation: dict[str, Any]) -> bool:
    """Fails closed: a scope with a field Radar does not know matches nothing. On 2026-11-04 a row written by hand
    into the store carried ``{"event": "EDMO Hubs Townhall"}``; the unknown field was skipped, the scope was then empty
    and the rule silenced ninety signals of every kind in a day. ``sender`` compares addresses and ``sender_name``
    compares display names, each from its own field: an empty name on either side («"" <anyone@example.org>») names
    nobody and matches nothing."""
    if not valid_scope(scope):
        return False
    for key in SCOPE_FIELDS:
        expected = scope.get(key)
        if not expected:
            continue
        if key == "sender":  # a rule may store the bare address or «Name <addr>»: compare by address, never by name
            address = sender_address(expected)
            if not address or address != sender_address(observation.get("sender")):
                return False
        elif key == "sender_name":  # the name a relay keeps beside its own address, decoded on both sides
            name = sender_name(expected)
            actual = sender_name(observation.get("sender_name") or observation.get("sender"))
            if not name or not actual or name != actual:
                return False
        elif str(observation.get(key) or "").lower() != str(expected).lower():
            return False
    return True


def _legacy_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """A scope written while ``sender`` also carried a display name («coderabbitai[bot]», saved on 2026-11-13) read as
    the ``sender_name`` it was meant to be. Without this, narrowing ``sender`` back to the address would silently drop
    the rules the owner already relies on."""
    sender = str(scope.get("sender") or "").strip()
    if not sender or "@" in sender or scope.get("sender_name"):
        return scope
    return {**{key: value for key, value in scope.items() if key != "sender"}, "sender_name": sender}


def names_only_scope(scope: dict[str, Any], effect: Any) -> bool:
    """A scope that names the sender and gives no address. The name is chosen by whoever writes the mail, so it may
    only lower: silent and digest can stand on it, notify and prefer need the address beside it."""
    return bool(scope.get("sender_name")) and not scope.get("sender") and effect not in NAME_ONLY_EFFECTS


def _usable(preference: dict[str, Any], observation: dict[str, Any], dimension: str) -> bool:
    if preference.get("status") != "active" or preference.get("dimension") != dimension:
        return False
    if preference.get("effect") not in EFFECTS:
        return False
    scope = _legacy_scope(dict(preference.get("scope") or {}))
    if preference.get("effect") == "silent" and not scope:
        return False  # a mute of everything is /radar pause, never a preference
    if names_only_scope(scope, preference.get("effect")):
        return False  # a name is chosen by whoever writes: it can silence, never raise
    return scope_matches(scope, observation)


def applicable(preferences: list[dict[str, Any]], observation: dict[str, Any], dimension: str = "notification") -> list[dict[str, Any]]:
    """Active preferences of one dimension whose scope matches, explicit ones first. A silence needs a scope: a rule
    that would mute everything is not a preference (that is ``/radar pause``), so one with an empty scope never applies.
    A rule scoped by display name alone never raises anything either: only silent and digest can stand on a name."""
    usable = [p for p in preferences if _usable(p, observation, dimension)]
    usable.sort(key=lambda p: 0 if p.get("origin") == "explicit" else 1)
    return usable
