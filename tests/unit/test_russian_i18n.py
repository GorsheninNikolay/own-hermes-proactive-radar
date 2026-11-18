"""Russian locale contracts; no live model or external actions."""
import asyncio
from string import Formatter

import pytest

from radar.i18n import STRINGS, language_name, language_of, t
from radar.jobs.prompts import build_job_prompt
from radar.pipeline.extract import extract
from radar.pipeline.consolidate import _lang


@pytest.mark.parametrize("code", ["ru", "ru-RU", "RU-ru"])
def test_russian_locale_resolution(code):
    assert language_of(code) == "ru"
    assert language_name(code) == "Russian"
    assert t(code, "draft") == "Предлагаемый ответ"


@pytest.mark.parametrize("code,name", [("en-US", "English"), ("es-ES", "Spanish"), ("xx", "English"), (None, "Spanish")])
def test_existing_locale_resolution(code, name):
    assert language_name(code) == name


def test_russian_catalog_has_all_keys_and_matching_placeholders():
    assert set(STRINGS["ru"]) == set(STRINGS["en"])
    fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field is not None}
    for key, text in STRINGS["en"].items():
        assert fields(STRINGS["ru"][key]) == fields(text), key


@pytest.mark.parametrize("code", ["ru", "ru-RU"])
def test_real_extract_requests_russian(code):
    class Gate:
        async def structured(self, *args, **kwargs):
            self.instructions = kwargs["instructions"]
            return {"proposed_reply": "Спасибо, подтверждаю."}
    gate = Gate()
    result = asyncio.run(extract(gate, [], owner={"language": code}, now="2026-11-18T00:00:00Z", facts=[], open_tasks=[]))
    assert "Russian" in gate.instructions
    assert result["proposed_reply"] == "Спасибо, подтверждаю."


def test_job_prompt_preserves_approved_draft_and_operation():
    draft = "Send this EXACT text.\nНе переводить!"
    prompt = build_job_prompt(task={"kind": "other", "title": "Test"}, proposal={"operation_id": "mail.send", "params": {"draft": draft}}, option="do", action_class="external", signals=[], facts=[], owner={"language": "ru-RU"}, workdir=None, grant={"at": "now", "label": "Да"})
    assert "Write the summary, findings and proposed reply in Russian." in prompt
    assert "<<<\n" + draft + "\n>>>" in prompt
    assert "Operation hint: mail.send" in prompt
    assert "send it exactly as it is, do not rewrite it" in prompt
    assert "OWNER APPROVAL:" in prompt


def test_consolidation_resolves_russian():
    assert _lang({"owner": {"language": "ru-RU"}}) == "Russian"


def test_russian_checklist_labels_preserve_identifiers():
    from radar.pipeline.checklists import LABELS, label, canonical_item
    assert set(LABELS["ru"]) == set(LABELS["es"])
    for item, translated in LABELS["ru"].items():
        assert label(item, "ru-RU") == translated
        assert canonical_item(translated, [item]) == item


def test_russian_dates_and_schedules():
    from radar.delivery.context import _MONTHS
    from radar.delivery.remind import describe_schedule
    from radar.render.cards import BUILTIN, _day_label, cron_label
    assert _MONTHS["ru"][0] == "янв"
    assert all(spec["label"]["ru"] for spec in BUILTIN.values())
    assert _day_label("2026-11-18T10:00:00Z", "ru-RU", "UTC")["weekday"] == "среда"
    assert cron_label("0 11 * * *", "ru-RU") == "каждый день в 11:00"
    assert cron_label("0 11 * * 1", "ru-RU") == "понедельник, в 11:00"
    assert describe_schedule("0 11 * * 1", "ru-RU") == "понедельник в 11:00"


def test_russian_trust_guide_keeps_policy_terms():
    from radar.trust import GUIDE, guide_text
    assert set(GUIDE["ru"]) == set(GUIDE["en"])
    text = guide_text("ru-RU")
    assert "одобрение" in text
    assert "trust.auto_external" in text
    assert "cautious" in text and "balanced" in text and "autonomous" in text
