"""Independent review regressions, exercised without live services."""
import asyncio
import pytest
from test_reply_understanding import _notice, _rt, _event
from conftest import active_config
from radar.delivery.telegram_ui import handle_text_reply
from radar.delivery.feedback import understand
from radar.pipeline.reconcile import family, same_family, reconcile
from radar.pipeline.checklists import word_stems
from radar.pipeline.conflicts import dated_days, away_checks
from radar.i18n import t
from radar.render.report import render_task_report


def test_report_localizes_checklist_without_mutation():
    task = {'id':'t','title':'Поездка','checklist':[{'item':'outbound transport booked','status':'missing'},{'item':'<custom>','status':'missing','note':'<note>'}]}
    report = render_task_report(task,signals=[],proposals=[],facts=[],language='ru')
    assert 'транспорт туда забронирован' in report
    assert 'outbound transport booked' not in report
    assert '&lt;custom&gt;' in report and '&lt;note&gt;' in report
    assert task['checklist'][0]['item'] == 'outbound transport booked'


def test_russian_hints_only_advertise_supported_approval():
    for key in ('reply_ack_unclear', 'review_draft', 'review_details'):
        text = t('ru', key, ref='', text='draft', label='Отправить', title='Title', rationale='', summary='')
        assert 'ответьте «да»' not in text
        assert 'номер' in text or 'кнопк' in text or 'нажмите' in text


def test_russian_number_approval_keeps_canonical_option(store):
    cfg = active_config()
    cfg['owner']['language'] = 'ru'
    transports = _notice(store, cfg, [('p','check',[{'id':'ok','label':'Верно'},{'id':'wrong','label':'Ошибка'}],'Проверить доставку')])
    asyncio.run(handle_text_reply(_rt(store,cfg,transports), _event('1')))
    assert store.get_proposal('p')['response']['option'] == 'ok'


@pytest.mark.parametrize('label,expected', [('Доставка',True),('Срок доставки',True),('Ожидаемый срок доставки',True),('Срок оплаты доставки',False),('Срок отмены доставки',False)])
@pytest.mark.parametrize('expectation', [False,True])
def test_delivery_estimate_is_not_payment_or_cancellation(label, expected, expectation):
    item = {'category':'purchase','title':'Посылка','entities':{'dates':[{'label':label,'when':'2026-11-22'}]}}
    if expectation:
        item['entities'] = {}
        item['expectations'] = [{'description':label,'by':'2026-11-22'}]
    assert dated_days(item) == (['2026-11-22'] if expected else [])
    trip = {'kind':'trip','title':'Поездка','entities':{'dates':[{'label':'Заезд','when':'2026-11-20'},{'label':'Выезд','when':'2026-11-24'}]}}
    assert bool(away_checks(item,[trip],language='ru')) == expected


def test_unicode_reconciliation_preserves_sent_identity():
    assert word_stems('Подтвердите доставку домой')
    old = {'id':'q1','operation_id':'ask','title':'Нужно ли бронировать гостиницу','params':{'fact':{'key':'поездка_гостиница'}},'status':'sent'}
    new = {**old,'params':{'fact':{'key':'гостиница_поездка'}}}
    class Rows:
        def list_proposals(self, **kw): return [old]
    kept, removed = reconcile(Rows(),'t',[new],'2026-11-18T10:00:00Z')
    assert removed == [] and kept[0]['existing_id'] == 'q1'
    reworded = {**new, 'title':'Зарезервировать жильё?'}
    kept, removed = reconcile(Rows(),'t',[reworded],'2026-11-18T10:00:00Z')
    assert removed == [] and kept[0]['existing_id'] == 'q1'
    check = {'operation_id':'check','title':'Подтвердите доставку домой'}
    assert same_family(family(check), family(check))
    assert not same_family(family(check),family({'operation_id':'check','title':'Проверить бронирование гостиницы'}))


@pytest.mark.parametrize('text', ['отклоняю отправку в Gmail', 'отклонить send it', 'отменить send it', '1 нет', 'не отправляй'])
@pytest.mark.parametrize('model', [False, True])
def test_russian_refusal_is_terminal_in_feedback_pipeline(store, text, model):
    cfg = active_config()
    cfg['owner']['language'] = 'ru'
    transports = _notice(store, cfg, [('p', 'web.act', [{'id':'do','label':'Отправить письмо в Gmail'}, {'id':'no','label':'Отклонить'}], 'Отправить письмо в Gmail')])
    rt = _rt(store, cfg, transports, answers=[{'intent':'approve','proposal_index':1,'option':'do'}] if model else None)
    row = store.outbox_by_platform_message('msg-1')
    verdict = asyncio.run(understand(rt.gate, text, outbox_row=row, store=store, language='ru'))
    assert verdict['intent'] == 'reject'
    asyncio.run(handle_text_reply(rt, _event(text)))
    assert store.get_proposal('p')['status'] == 'declined'
    assert not store.list_jobs(limit=10)
    assert not rt.llm.calls


@pytest.mark.parametrize('text', ['да', 'возможно отправить в Gmail', 'Отправить письмо в Gmail?', 'да, отменить', 'Gmail', 'maybe Gmail', 'ok'])
def test_ambiguous_russian_never_authorizes_pipeline(store, text):
    cfg = active_config()
    cfg['owner']['language'] = 'ru'
    transports = _notice(store, cfg, [('p','web.act',[{'id':'do','label':'Отправить письмо в Gmail'},{'id':'no','label':'Отклонить'}],'Отправить письмо в Gmail')])
    rt = _rt(store, cfg, transports, answers=[{'intent':'approve','proposal_index':1,'option':'do'}])
    asyncio.run(handle_text_reply(rt, _event(text)))
    assert store.get_proposal('p')['status'] not in ('accepted','waiting','executing','succeeded')
    assert not store.list_jobs(limit=10)
