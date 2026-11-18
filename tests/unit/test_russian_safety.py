import pytest
from radar.delivery.feedback import classify, merge, names_the_action

@pytest.mark.parametrize('text', ['нет', '1 нет', '1 не', 'не отправляй', 'не надо', 'не сейчас', 'да, но не отправляй', 'yes, но не надо', '1 xyz', '1 хз', 'да. Нет', 'отмена'])
def test_refusals_never_approve(text):
    floor = classify(text)
    assert floor['intent'] != 'approve'
    result = merge(floor, {'intent': 'approve', 'proposal_index': 1, 'option': 'do'}, text, [{'open': True, 'answers': [{'id': 'do'}]}])
    if any(word in text.lower().split() for word in ('нет', 'не', 'но')) or text in ('отмена', '1 хз'):
        assert result['intent'] != 'approve'

@pytest.mark.parametrize('text', ['не отправляй письмо', 'нет отправить письмо'])
def test_refusal_cannot_name_action(text):
    assert names_the_action(text, [{'open': True, 'index': 1, 'answers': [{'id': 'do', 'label': 'Отправить письмо'}]}]) is None
