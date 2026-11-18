"""Owner-reported question/refusal and delivery-date regressions."""
import asyncio
import pytest

from conftest import active_config
from test_reply_understanding import _notice, _rt, _event
from radar.delivery.telegram_ui import handle_text_reply


@pytest.mark.parametrize('language', ['en', 'ru'])
@pytest.mark.parametrize('text,index', [
    ('нет', 0), ('отмена', 0), ('не отправляй', 0),
    ('отклоняю отправку в Gmail', 0), ('отменить send it', 0), ('1 нет', 1),
])
def test_explicit_refusal_only_declines_its_intended_targets(store, language, text, index):
    cfg = active_config()
    cfg['owner']['language'] = language
    options = [{'id':'do','label':'Отправить'}, {'id':'no','label':'Отклонить'}]
    transports = _notice(store, cfg, [('p1','web.act',options,'Письмо'), ('p2','web.act',options,'Письмо')])
    rt = _rt(store,cfg,transports,answers=[{'intent':'approve','proposal_index':1,'option':'do'}])
    asyncio.run(handle_text_reply(rt,_event(text)))
    assert store.get_proposal('p1')['status'] == 'declined'
    assert store.get_proposal('p1')['response']['option'] == 'no'
    assert store.get_proposal('p2')['status'] == ('sent' if index else 'declined')
    assert not store.list_jobs(limit=10) and not rt.llm.calls


@pytest.mark.parametrize('text', ['3', '3 нет', '1'])
@pytest.mark.parametrize('language', ['en', 'ru'])
def test_invalid_or_closed_number_never_selects_another_proposal(store, text, language):
    cfg = active_config()
    cfg['owner']['language'] = language
    options = [{'id':'do','label':'Отправить'}, {'id':'no','label':'Отклонить'}]
    transports = _notice(store,cfg,[('p1','web.act',options,'Письмо'),('p2','web.act',options,'Письмо')])
    store.respond_proposal('p1',decision='declined',response={'option':'no'},now='2026-10-19T10:00:00Z')
    before = [store.get_proposal(p) for p in ('p1','p2')]
    asyncio.run(handle_text_reply(_rt(store,cfg,transports),_event(text)))
    assert [store.get_proposal(p) for p in ('p1','p2')] == before
    assert not store.list_jobs(limit=10)


@pytest.mark.parametrize('language', ['en', 'ru'])
@pytest.mark.parametrize('model', [None, 'approve', 'reject'])
@pytest.mark.parametrize('text', [
    'Когда отменят рейс?', 'Когда отменят рейс', '1 Когда отменят рейс?',
    'Почему отклонили оплату?', '2 почему нет доставки?',
    'Отмена рейса уже подтверждена?', '1 нет ли обновлений?',
    'отменили рейс', 'отклонён платёж', 'да, отменить',
])
def test_questions_and_ambiguous_text_preserve_both_sent_proposals(store, language, model, text):
    cfg = active_config()
    cfg['owner']['language'] = language
    options = [{'id':'do', 'label':'Отменить рейс'}, {'id':'no', 'label':'Отклонить'}]
    transports = _notice(store, cfg, [('p1','web.act',options,'Отменить рейс'), ('p2','web.act',options,'Отменить рейс')])
    before = [store.get_proposal(p) for p in ('p1','p2')]
    rt = _rt(store, cfg, transports, answers=[{'intent':model,'proposal_index':1,'option':'do'}] if model else None)
    result = asyncio.run(handle_text_reply(rt, _event(text)))
    assert result['action'] == 'rewrite'
    assert result['text'].endswith(text)
    assert [store.get_proposal(p) for p in ('p1','p2')] == before
    assert not store.list_jobs(limit=10)
    assert not rt.llm.calls


@pytest.mark.parametrize('language', ['en', 'ru', 'es'])
@pytest.mark.parametrize('expectation', [False, True])
@pytest.mark.parametrize('label,expected', [
    ('Delivery', True), ('Delivery due date', True), ('Доставка', True),
    ('Срок доставки', True), ('Entrega', True),
    ('Delivery payment due date', False), ('Delivery cancellation deadline', False),
    ('Delivery refund due date', False), ('Срок оплаты доставки', False),
    ('Срок отмены доставки', False), ('Срок возврата средств за доставку', False),
])
def test_delivery_due_date_warns_in_both_arrival_orders(language, expectation, label, expected):
    from radar.pipeline.conflicts import dated_days, away_checks
    parcel = {'category':'purchase', 'kind':'purchase', 'title':'Parcel',
              'entities':{'dates':[{'label':label,'when':'2026-11-22'}]}}
    if expectation:
        parcel['entities'] = {}
        parcel['expectations'] = [{'description':label,'by':'2026-11-22'}]
    trip = {'category':'trip', 'kind':'trip', 'title':'Trip', 'entities':{'dates':[
        {'label':'Check-in','when':'2026-11-20'}, {'label':'Check-out','when':'2026-11-24'}]}}
    assert dated_days(parcel) == (['2026-11-22'] if expected else [])
    for incoming, existing in ((parcel,trip), (trip,parcel)):
        checks = away_checks(incoming,[existing],language=language)
        assert len(checks) == int(expected)
        if expected:
            assert checks[0]['severity'] == 'high' and checks[0]['ask_user'] is True
            assert '22/11' in checks[0]['description']
