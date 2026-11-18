from radar.pipeline.reconcile import key_tokens
from radar.pipeline.conflicts import away_checks, travel_days, dated_days
from radar.i18n import language_of

def test_unicode_fact_tokens():
    assert key_tokens('позиция_по_проекту') == frozenset({'позиция', 'проекту'})
    assert key_tokens('ПРОЕКТ_ответ') == key_tokens('проект_ответ')

def test_russian_conflict_both_orders_and_deadlines():
    trip = {'kind': 'trip', 'category': 'trip', 'title': 'Поездка', 'entities': {'dates': [{'label': 'Заезд', 'when': '2026-11-20'}, {'label': 'Обратный рейс', 'when': '2026-11-24'}]}}
    parcel = {'kind': 'purchase', 'category': 'purchase', 'title': 'Посылка', 'entities': {'dates': [{'label': 'Доставка', 'when': '2026-11-22'}]}}
    assert away_checks(parcel, [trip], language='ru')[0]['severity'] == 'high'
    assert away_checks(trip, [parcel], language='ru')[0]['ask_user']
    assert travel_days({'entities': {'dates': [{'label': 'Срок отмены рейса', 'when': '2026-11-19'}]}}) is None
    assert dated_days({'entities': {'dates': [{'label': 'Срок оплаты доставки', 'when': '2026-11-22'}]}}) == []

def test_normalize_locale_whitespace_and_underscore():
    assert language_of(' RU_ru ') == 'ru'
    assert language_of(' fr-FR ') == 'en'
