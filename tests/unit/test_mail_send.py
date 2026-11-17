"""What a message Radar sends for the owner may be (2026-11-16).

The owner approved «send the signed sheet» and what went out was a text written before the sheet existed, with an
unfilled «[DNI e IBAN]», a subject line inside the body and no file: the reminder had not shown the text, the send
could not attach, and nothing checked either.
"""
from __future__ import annotations

import asyncio
import base64
import email

from conftest import NOW, FakeContext, active_config, verify_destination
from test_native import NOW_S, Mail, _proposal, _task_with_email

from radar.delivery.dispatch import build_reminder
from radar.delivery.notice import build_interrupt, mail_block
from radar.jobs.service import enqueue_job_for_proposal, job_block_reason
from radar.mailtext import attachment_facts, unsendable, verify_attachments
from radar.operations import native
from radar.pipeline import act, reason
from radar.providers.cli import mime_raw
from radar.providers.mail_gmail_mcp import GmailMcpProvider
from radar.runtime import Runtime

SENT = ("Asunto: Hoja de gastos Semana Impulso TIC 2026 – David. Hola Rosa, gracias por la hoja. Te devuelvo la hoja firmada "
        "(adjunto extracto). Datos para abono: [DNI e IBAN]. Un saludo")
SUBJECT = "Hoja de gastos Semana Impulso TIC 2026"


class AttachingMail(Mail):
    def __init__(self, *, attach=True):
        super().__init__()
        self.attach = attach

    def capabilities(self):
        return {"reply": True, "attach": self.attach}

    def reply(self, message_id, body, *, reply_all=False, attachments=None):
        self.calls.append(("reply", message_id, body, list(attachments or [])))
        return {"result": "Email sent. Message ID: 1a1558945ae274e7"}


def test_a_text_with_an_unfilled_field_or_a_subject_line_is_not_a_reply():
    assert unsendable(SENT, subject="Re: " + SUBJECT) == "placeholder"
    assert unsendable(SENT.replace("[DNI e IBAN]", "en la hoja"), subject=SUBJECT) == "subject_header"
    # Told by its typography, not by its words: it holds in any language.
    for field in ("Hola <tu nombre>,", "Total: ____ euros", "IBAN: {{iban}}", "Teléfono: XXXXXXXXX", "金額は【金額】です", "Sehr geehrte [Name],"):
        assert unsendable(field) == "placeholder", field
    assert unsendable("件名：経費精算書 2026 こんにちは", subject="Re: 経費精算書 2026") == "subject_header"
    assert unsendable("") == "empty" and unsendable("   ") == "empty"
    # What a real reply carries is not a field: a footnote, a link, an address, a greeting with a colon.
    fine = "Hola Rosa: te confirmo [1] y mira [la hoja](https://example.org/h). Escribe a <rosa@example.org> o a <https://example.org>. Un saludo"
    assert unsendable(fine, subject=SUBJECT) == ""
    assert unsendable("Nota: te envío la hoja de gastos mañana.", subject=SUBJECT) == ""
    for plain in ("TODO EL EQUIPO te manda un abrazo.", "Como dijo ayer [...], si a < b y c > d entonces [2]."):
        assert unsendable(plain, subject=SUBJECT) == "", plain


def test_a_step_that_writes_such_a_text_does_not_leave_it_as_the_reply(store):
    _task_with_email(store)
    task = store.get_task("t1")
    kept = act.remember_draft(store, task, {"proposed_reply": SENT}, NOW_S)
    assert kept["text"].startswith("Hi Hans")  # the earlier, sendable one stays in force
    assert act.remember_draft(store, store.get_task("t1"), {"proposed_reply": "Hi Hans, here is the fix."}, NOW_S)["text"] == "Hi Hans, here is the fix."
    # Second lock, at the send: whatever got stored, it has no way to run.
    stale = _proposal(store, params={"draft": SENT})
    assert native.plan(store, stale, store.get_task("t1"), "send") is None
    assert job_block_reason(store, active_config(), proposal=stale, now_dt=NOW) == "no_safe_executor"


def test_any_document_of_the_owner_can_travel_but_never_a_credential(tmp_path):
    """Owner's rule, 2026-11-16: a document another session made is as sendable as one sent in a chat; where it lives
    is not a rule. What may never travel is a credential, a hidden file, or a file that is not there."""
    elsewhere = tmp_path / "informes" / "gastos"
    elsewhere.mkdir(parents=True)
    sheet = elsewhere / "hoja firmada.docx"
    sheet.write_bytes(b"signed sheet")
    (elsewhere / "recibo.pdf").write_bytes(b"receipt")
    facts = attachment_facts([str(sheet), str(elsewhere / "recibo.pdf")])
    assert [f["name"] for f in facts] == ["hoja firmada.docx", "recibo.pdf"] and facts[0]["size"] == 12 and len(facts[0]["sha256"]) == 64
    assert attachment_facts([]) == []
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_bytes(b"key")
    hermes = tmp_path / ".hermes"
    (hermes / "radar" / "secrets").mkdir(parents=True)
    (hermes / ".env").write_bytes(b"TOKEN=x")
    (hermes / "radar" / "secrets" / "consent.key").write_bytes(b"k")
    (elsewhere / "link.docx").symlink_to(ssh / "id_ed25519")  # a link is judged by what it points to
    (elsewhere / ".hidden").write_bytes(b"x")
    (elsewhere / "empty.txt").write_bytes(b"")
    for bad in (ssh / "id_ed25519", hermes / ".env", hermes / "radar" / "secrets" / "consent.key", elsewhere / "link.docx", elsewhere / ".hidden",
                elsewhere / "empty.txt", elsewhere / "nope.pdf", elsewhere):
        assert attachment_facts([str(sheet), str(bad)]) is None, bad  # one bad file refuses the whole message
    assert attachment_facts([str(sheet)] * 6) is None
    # The approval is for these bytes.
    assert verify_attachments(facts) == [str(sheet), str(elsewhere / "recibo.pdf")]
    sheet.write_bytes(b"another sheet")
    try:
        verify_attachments(facts)
    except PermissionError as exc:
        assert "changed" in str(exc)
    else:
        raise AssertionError("a changed file was accepted")


def test_the_approved_files_travel_with_the_reply_or_nothing_is_sent(store, tmp_path):
    cfg = active_config(sources=[{"id": "gmail-a", "kind": "gmail", "address": "me@example.org", "server": "gmail-a", "provider": "gmail_mcp"}])
    verify_destination(store)
    _task_with_email(store)
    rt = Runtime(FakeContext(cfg, llm=None, call_mcp=lambda *a, **k: None), store, cfg, worker_id="w", clock=lambda: NOW, hermes_home=str(tmp_path))
    folder = tmp_path / "radar" / "reports"
    folder.mkdir(parents=True)
    sheet = folder / "hoja.docx"
    sheet.write_bytes(b"signed sheet")
    facts = attachment_facts([str(sheet)])

    def run(pid, mail):
        proposal = _proposal(store, pid=pid, params={"draft": "Hi Hans, the signed sheet is attached.", "attachments": facts})
        job = enqueue_job_for_proposal(store, cfg, proposal=proposal, option="send", now_dt=NOW)
        assert job["kind"] == "native" and '"sha256"' in job["prompt"]  # the files are part of what was consented
        rt.write_provider = lambda kind, account="": mail
        claimed = [j for j in store.claim_queued_jobs(NOW_S, "2026-10-19T10:10:00Z", 5) if j["id"] == job["id"]]
        outcome = asyncio.run(native.run_job(rt, claimed[0]))
        return outcome

    mail = AttachingMail()
    sent = run("ok", mail)
    assert sent.status == "succeeded" and mail.calls[0] == ("reply", "m-hans-1", "Hi Hans, the signed sheet is attached.", [str(sheet)])
    assert not any(call[0] == "send_draft" for call in mail.calls)  # a saved draft has no files: never that road


def test_a_file_that_changed_or_a_provider_that_cannot_attach_sends_nothing(store, tmp_path):
    folder = tmp_path / "radar" / "reports"
    folder.mkdir(parents=True)
    sheet = folder / "hoja.docx"
    sheet.write_bytes(b"signed sheet")
    facts = attachment_facts([str(sheet)])
    params = {"message_id": "m1", "body": "Attached.", "attachments": facts, "account": "me@example.org"}
    plain = AttachingMail(attach=False)
    for provider, change in ((plain, False), (AttachingMail(), True)):
        if change:
            sheet.write_bytes(b"swapped after the owner said yes")
        try:
            native._gmail_reply(params, provider)
        except PermissionError:
            pass
        else:
            raise AssertionError("the reply went out")
        assert provider.calls == []


def test_every_notice_that_asks_to_send_mail_shows_the_text_and_the_files(store):
    _task_with_email(store)
    task = store.get_task("t1")
    text = "Hi Hans, could you send screenshots?"
    store.create_task_proposal(proposal_id="m1", task_id="t1", title="Enviar la respuesta a Hans", reason_text="", action_class="external", operation_id="gmail.reply",
                               params={"draft": text}, options=[{"id": "send", "label": "Enviar"}, {"id": "no", "label": "No"}], urgency="normal",
                               expires_at="2026-10-22T10:00:00Z", fingerprint="m1", now=NOW_S)
    bare = store.get_proposal("m1")
    selection = {"items": [{"task": task, "decision": bare}], "decisions": [bare], "news": []}
    reminder = build_reminder(selection, "La respuesta a Hans está lista. ¿La envío?", language="es")
    assert reminder["text"].startswith("La respuesta a Hans está lista. ¿La envío?")
    assert "<b>Texto que se enviará:</b>" in reminder["text"] and text in reminder["text"] and "Sin adjuntos: solo sale este texto." in reminder["text"]
    with_files = {**bare, "params": {"draft": text, "attachments": [{"path": "/x/hoja firmada.docx", "name": "hoja firmada.docx", "size": 34567, "sha256": "0" * 64}]}}
    block = mail_block(with_files, task, "en")
    assert "<b>Text that will be sent:</b>" in block and "<b>Attachments:</b> hoja firmada.docx (35 kB, /x)" in block and "No attachments" not in block
    # The text shown is the text the send uses, also when it lives on the task and not on the step.
    on_task = {**bare, "params": {}}
    assert native.mail_text(on_task, task) == native.plan(store, {**on_task, "response": {"option": "send"}}, task, "send")["params"]["body"]
    assert native.mail_text(on_task, task) in mail_block(on_task, task, "es")
    assert "Texto que se enviará" in build_interrupt(task, [bare], "¿La envío?", language="es")["text"]
    # A step that is not mail shows no such block.
    assert mail_block({**bare, "operation_id": "investigate"}, task, "es") == ""


def test_the_plan_names_the_files_and_the_code_checks_them(tmp_path):
    plan = reason.validate_plan({"task_match": {"decision": "new"}, "task": {"title": "Hoja"}, "notify": {"disposition": "digest"}, "proposals": [
        {"title": "Enviar la hoja", "action_class": "external", "operation": "gmail.reply", "basis": "owner_decision", "attachments": ["/a/hoja.docx", "", 7]},
        {"title": "Mirar", "action_class": "read", "operation": "investigate", "attachments": ["/a/x"]}]})
    assert plan["proposals"][0]["attachments"] == ["/a/hoja.docx"] and "attachments" not in plan["proposals"][1]


def test_the_providers_carry_the_files():
    seen = {}

    def call_mcp(server, tool, args, timeout=30):
        seen.update(server=server, tool=tool, args=args)
        return {"content": [{"type": "text", "text": "Email sent successfully with ID: abc"}]}

    provider = GmailMcpProvider(call_mcp, "gmail-a", allow_write=True)
    assert provider.capabilities()["attach"] is True and GmailMcpProvider(call_mcp, "gmail-a").capabilities()["attach"] is False
    provider.reply("m1", "Attached.", reply_all=True, attachments=["/x/hoja.docx"])
    assert seen["args"] == {"messageId": "m1", "body": "Attached.", "attachments": ["/x/hoja.docx"]}
    provider.reply("m1", "Plain.")
    assert seen["args"] == {"messageId": "m1", "body": "Plain."}


def test_the_command_line_mail_is_built_with_its_files(tmp_path):
    sheet = tmp_path / "hoja.docx"
    sheet.write_bytes(b"signed sheet")
    raw = mime_raw(to="rosa@example.org", subject="Re: Hoja", body="Adjunta va.", in_reply_to="<id@x>", attachments=[str(sheet)])
    message = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    parts = list(message.walk())
    assert message.is_multipart() and message["In-Reply-To"] == "<id@x>" and message["To"] == "rosa@example.org"
    assert parts[1].get_payload(decode=True) == "Adjunta va.".encode() and parts[2].get_filename() == "hoja.docx" and parts[2].get_payload(decode=True) == b"signed sheet"
    assert not email.message_from_bytes(base64.urlsafe_b64decode(mime_raw(to="a@b.c", subject="s", body="b"))).is_multipart()
