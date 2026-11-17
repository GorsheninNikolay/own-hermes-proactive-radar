from __future__ import annotations

import pytest

from radar.delivery.learn import preference_from_fields
from radar.pipeline.triage import triage_signal
from radar.preferences import (
    SCOPE_FIELDS as STORE_FIELDS,
    applicable,
    new_preference,
    scope_matches,
    sender_name,
)

GITHUB = "notifications@github.com"
CODERABBIT = f'"coderabbitai[bot]" <{GITHUB}>'
DEPENDABOT = f'"dependabot[bot]" <{GITHUB}>'
# The rule the review asked for: the relay's address and, beside it, the name that tells one bot from another.
BOT_RULE = {"sender": GITHUB, "sender_name": "coderabbitai[bot]"}


def _observation(sender: str, **extra: str) -> dict[str, str]:
    return {"sender": sender, "kind": "email", "source_kind": "gmail", **extra}


def _preference(scope: dict[str, str], effect: str = "silent", dimension: str = "notification") -> dict[str, object]:
    """A record as the store holds it, without going through the write-side checks."""
    return {"id": "pref-x", "status": "active", "dimension": dimension, "scope": scope, "effect": effect,
            "exceptions": [], "origin": "explicit"}


def test_a_bot_rule_names_the_bot_and_leaves_the_rest_of_github_alone():
    """GitHub relays every App from its own address, so the name is the only thing that narrows the rule."""
    assert scope_matches(BOT_RULE, _observation(CODERABBIT)) is True
    assert scope_matches(BOT_RULE, _observation(DEPENDABOT)) is False
    assert scope_matches(BOT_RULE, _observation(f'"Adam Smith" <{GITHUB}>')) is False


def test_the_name_cannot_be_borrowed_from_another_address():
    """For notify or prefer this would let anyone raise their own mail by writing that name."""
    assert scope_matches(BOT_RULE, _observation(f'"coderabbitai[bot]" <evil@example.org>')) is False
    assert scope_matches(BOT_RULE, _observation("coderabbitai[bot]@evil.example")) is False


def test_an_empty_or_missing_name_matches_nothing():
    """A silence scoped by «""» used to reduce both sides to "" and mute every bare address."""
    assert scope_matches({"sender": '""'}, _observation("anyone@example.org")) is False
    assert scope_matches({"sender": '""'}, _observation("")) is False
    assert scope_matches({"sender": GITHUB, "sender_name": '""'}, _observation(CODERABBIT)) is False
    assert scope_matches({"sender_name": '""'}, _observation(CODERABBIT)) is False
    assert scope_matches(BOT_RULE, _observation(GITHUB)) is False  # no name on the signal, a name in the rule
    assert scope_matches({"sender_name": "coderabbitai[bot]"}, _observation(f"<{GITHUB}>")) is False
    assert sender_name('"" <anyone@example.org>') == "" and sender_name("anyone@example.org") == ""


def test_a_name_only_rule_is_refused_for_notify_and_prefer():
    """The name is chosen by whoever writes, so alone it may only lower: silent and digest are fine."""
    for effect in ("notify", "prefer"):
        with pytest.raises(ValueError):
            new_preference("p", instruction="x", scope={"sender_name": "coderabbitai[bot]"}, effect=effect)
        with pytest.raises(ValueError):  # the radar_preference tool, before the record is built
            preference_from_fields({"instruction": "x", "effect": effect, "scope": {"sender_name": "coderabbitai[bot]"}})
    preference = new_preference("p", instruction="x", scope={"sender_name": "coderabbitai[bot]"}, effect="silent")
    assert preference["scope"] == {"sender_name": "coderabbitai[bot]"}
    fields = preference_from_fields({"instruction": "x", "effect": "silent",
                                     "scope": {"sender": GITHUB, "sender_name": "coderabbitai[bot]"}})
    assert fields["scope"] == {"sender": GITHUB, "sender_name": "coderabbitai[bot]"}

    observation = _observation(CODERABBIT)
    name_only = {"sender_name": "coderabbitai[bot]"}
    assert applicable([_preference(name_only)], observation) != []
    assert applicable([_preference(name_only, effect="digest")], observation) != []
    assert applicable([_preference(name_only, effect="prefer")], observation) == []
    assert applicable([_preference(name_only, effect="notify")], observation) == []


def test_a_name_value_in_sender_keeps_matching_by_address_only():
    """«Name <addr>» is the form a model is most likely to write: it narrows nothing, exactly as before."""
    assert scope_matches({"sender": CODERABBIT}, _observation(CODERABBIT)) is True
    assert scope_matches({"sender": CODERABBIT}, _observation(DEPENDABOT)) is True  # same mailbox, other name
    assert scope_matches({"sender": CODERABBIT}, _observation(f'"Adam Smith" <{GITHUB}>')) is True
    assert scope_matches({"sender": CODERABBIT}, _observation('"Adam Smith" <adam@example.org>')) is False


def test_an_rfc_2047_name_is_decoded_on_both_sides():
    """A header arrives encoded («=?UTF-8?Q?...?=») and not every source decodes it: compare the decoded name."""
    encoded = "=?UTF-8?Q?Notificaci=C3=B3n?= <bot@example.org>"
    assert sender_name(encoded) == "notificación"
    assert sender_name('"Notificación" <bot@example.org>') == "notificación"
    assert scope_matches({"sender_name": "Notificación"}, _observation(encoded)) is True
    assert scope_matches({"sender_name": "notificación"}, _observation('"Notificación" <bot@example.org>')) is True
    assert scope_matches({"sender_name": "notificación"}, _observation('"Avisos" <bot@example.org>')) is False


def test_a_sender_that_is_not_an_address_keeps_its_meaning_whatever_the_effect():
    """`sender` never turns into a name: a source whose sender is a handle is compared as written, also to raise."""
    handle = {"sender": "octocat", "kind": "work_item", "source_kind": "github"}
    for effect in ("silent", "digest", "notify", "prefer"):
        assert applicable([_preference({"sender": "octocat"}, effect=effect)], handle) != []
    assert applicable([_preference({"sender": "coderabbitai[bot]"})], _observation(CODERABBIT)) == []  # a name goes in sender_name


def test_a_name_rule_silences_only_that_bot_in_triage():
    preference = new_preference(
        "silence:coderabbit", instruction="Nunca avisar de los correos de CodeRabbit.",
        scope={"sender": GITHUB, "sender_name": "coderabbitai[bot]", "kind": "email"}, effect="silent",
        origin="explicit",
    )
    bot = {"id": "x", "kind": "email", "title": "Re: [jacanales/devops] fix(hermes): … (PR #439)",
           "snippet": "", "meta": {"sender": CODERABBIT, "account": "me@example.org", "source_kind": "gmail"}}
    human = {"id": "y", "kind": "email", "title": "Re: [jacanales/devops] fix(hermes): … (PR #439)",
             "snippet": "", "meta": {"sender": f'"Adam Smith" <{GITHUB}>', "account": "me@example.org",
                                      "source_kind": "gmail"}}
    decision = triage_signal(bot, [preference])
    assert decision.keep is False and decision.reason == "preference:silence:coderabbit"
    assert triage_signal(human, [preference]).keep is True


def test_the_model_is_offered_the_stores_scope_fields_except_the_one_only_the_code_writes():
    """The pipeline schema and the radar_preference tool take their fields from the store's list, so a field offered
    is one the record can hold. `subject_stem` stays out of both: it comes from the subject of a muted mail, and a
    stem a model made up would be a rule that matches nothing."""
    from radar.pipeline.schemas import PREFERENCE_SCHEMA, SCOPE_FIELDS as PIPELINE_FIELDS
    from radar.preferences import MODEL_SCOPE_FIELDS
    from radar.schemas.tools import PREFERENCE as TOOL

    offered = [field for field in STORE_FIELDS if field != "subject_stem"]
    assert "subject_stem" in STORE_FIELDS and "sender_name" in offered
    assert list(MODEL_SCOPE_FIELDS) == offered == list(PIPELINE_FIELDS)
    assert list(TOOL["parameters"]["properties"]["scope"]["properties"]) == offered
    assert list(PREFERENCE_SCHEMA["properties"]["scope"]["properties"]) == offered
