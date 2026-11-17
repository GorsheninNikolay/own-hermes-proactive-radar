"""A conversation is compared with the tasks the owner was told about, or answered, in that same chat (2026-11-16).

The owner answered a notice about an expense sheet and went on working on it with the agent in the same chat. Only
tasks born in a session were compared with a conversation, so it became a new task; and it was judged half an hour
later, when the mail had been sent and its task closed, so the new task asked for the send again.
"""
from __future__ import annotations

from datetime import timedelta

from conftest import NOW, active_config, extract_answer, plan_answer, verify_destination

from radar.pipeline import act, correlate, extract as extract_step, reason
from radar.sources.session import SOURCE_ID

T = "2026-10-19T10:00:00Z"
SID = "20261019_105200_abc123"


def _at(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _turn(store, signal_id, minutes, text, *, sid=SID, platform="telegram"):
    store.add_signal(signal_id=signal_id, source_id=SOURCE_ID, kind="session_turn", occurred_at=_at(minutes), external_ref=signal_id, group_key=f"session:{sid}",
                     title=text[:80], snippet=text, meta={"session_id": sid, "platform": platform, "user_text": text, "assistant_text": ""},
                     fingerprint=signal_id, now=_at(minutes))
    return store.get_signal(signal_id)


def _mail_task(store, task_id="sheet", title="Hoja de gastos Semana Impulso TIC 2026"):
    store.create_task(task_id=task_id, kind="routine", title=title, summary="", entities={}, expectations=[], checklist=[], now=T)
    return task_id


def _notice(store, task_id, minutes, outbox_id="o1"):
    store.enqueue_notification(outbox_id=outbox_id, destination_id="configured:primary", followup_id=None, proposal_id=None, notification_key=outbox_id,
                               payload={"text": "¿Tuviste gastos?"}, now=_at(minutes), task_id=task_id, kind="digest")
    store.db.execute("UPDATE outbox SET status='sent', updated_at=? WHERE id=?", (_at(minutes), outbox_id))


def _answer(store, task_id, minutes):
    store.add_signal(signal_id=f"a-{task_id}", source_id=SOURCE_ID, kind="user_reply", occurred_at=_at(minutes), external_ref=f"a-{task_id}", group_key=f"task:{task_id}",
                     title="Sí, tuve gastos", snippet="Sí, tuve gastos", meta={"task_id": task_id, "platform": "telegram"}, fingerprint=f"a-{task_id}", now=_at(minutes))


def test_a_chat_that_follows_a_notice_is_compared_with_the_task_of_that_notice(store):
    cfg = active_config()
    verify_destination(store)
    store.ensure_local_observation_source(T, 30)
    _mail_task(store)
    _mail_task(store, "other", "Factura de la luz")
    _notice(store, "sheet", 0)
    _notice(store, "other", -600, "o-old")  # told ten hours before: not this conversation
    _answer(store, "sheet", 6)
    turns = [_turn(store, "t1", 22, "Te paso el zip con los justificantes"), _turn(store, "t2", 28, "Sí, es mi firma")]
    related = correlate.related_tasks(store, cfg, turns, [SID], NOW + timedelta(minutes=61))
    assert [(t["id"], t["related"]) for t in related] == [("sheet", ["answered"])]
    candidates = correlate.candidate_tasks(store, extract_step.validate_extract(extract_answer()), session_id=SID, session_ids=[SID], related=related)
    assert candidates[0]["id"] == "sheet" and candidates[0]["related"] == ["answered"]
    # The link stays: a later turn of the same thread still finds the task, with no notice near it.
    later = [_turn(store, "t3", 900, "¿Ha contestado Rosa?")]
    assert [t["id"] for t in correlate.related_tasks(store, cfg, later, [SID], NOW + timedelta(minutes=901))] == ["sheet"]
    # A chat on another platform is not where the notice went.
    desk = [_turn(store, "d1", 25, "Otra cosa", sid="desk-1", platform="desktop")]
    assert correlate.related_tasks(store, cfg, desk, ["desk-1"], NOW + timedelta(minutes=61)) == []


def test_a_task_closed_meanwhile_is_still_the_one_the_chat_was_about_and_stays_closed(store):
    cfg = active_config()
    verify_destination(store)
    store.ensure_local_observation_source(T, 30)
    _mail_task(store)
    _notice(store, "sheet", 0)
    _answer(store, "sheet", 6)
    turns = [_turn(store, "t1", 22, "Te paso el zip con los justificantes")]
    store.set_task_status("sheet", "done", now=_at(47), reason="sent")  # the mail went out before the chat was judged
    related = correlate.related_tasks(store, cfg, turns, [SID], NOW + timedelta(minutes=61))
    assert [(t["id"], t["status"]) for t in related] == [("sheet", "done")]
    # The conversation lands on it: nothing reopens, nothing is asked, whatever the plan wanted.
    again = {"title": "¿Envío a Rosa la hoja firmada?", "rationale": "", "action_class": "read", "operation": "ask", "when": "", "urgency": "normal",
             "options": [{"id": "si", "label": "Sí"}, {"id": "no", "label": "No"}]}
    plan = plan_answer(task_match={"decision": "advances", "task_id": "sheet", "why": "same sheet"}, task={"title": "Hoja pendiente de envío", "status": "needs_user"},
                       proposals=[again], notify={"disposition": "digest", "urgency": "today", "importance": "high", "reason": "x"})
    result = act.apply(store, cfg, signals=turns, extract=extract_step.validate_extract(extract_answer()), plan=reason.validate_plan(plan),
                       now_dt=NOW + timedelta(minutes=61), preferences=[])
    assert result.task_id == "sheet" and store.get_task("sheet")["status"] == "done" and result.disposition == "silent"
    assert store.list_proposals(task_id="sheet") == [] and [t["id"] for t in store.list_tasks(limit=10)] == ["sheet"]
    assert "t1" in {s["id"] for s in store.signals_for_task("sheet")}
    # Closed long ago, it is no longer offered.
    assert correlate.related_tasks(store, cfg, turns, [SID], NOW + timedelta(hours=72)) == []


def test_a_task_born_in_a_chat_is_linked_to_it(store):
    cfg = active_config()
    verify_destination(store)
    store.ensure_local_observation_source(T, 30)
    turn = _turn(store, "t1", 0, "Recuérdame renovar el dominio")
    result = act.apply(store, cfg, signals=[turn], extract=extract_step.validate_extract(extract_answer()),
                       plan=reason.validate_plan(plan_answer(task={"title": "Renovar el dominio"})), now_dt=NOW + timedelta(minutes=31), preferences=[])
    assert [(t["id"], t["related"]) for t in store.tasks_related_to_sessions([SID])] == [(result.task_id, ["born"])]
    assert store.link_task_session("", SID, "born", now=T) is False and store.link_task_session(result.task_id, SID, "seen", now=T) is False
