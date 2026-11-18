from radar.render.report import render_task_report

def test_report_russian_labels_and_escaping():
    report = render_task_report({'id': 't', 'kind': 'trip', 'status': 'open', 'title': '<script>x</script>'}, signals=[], proposals=[], facts=[{'key': 'x', 'value': '<img>'}], jobs=[{'kind': 'research', 'status': 'running'}], language='ru')
    for label in ('Поездка', 'Открыто', 'Задания', 'Факты', 'Выполняется'):
        assert label in report
    assert '<script>x</script>' not in report and '&lt;img&gt;' in report
