import pytest

from linebeads.pipeline import execute, open_fixture, correct


def window_member(records, lo, hi):
    for row in records:
        if lo <= row['day'] < hi and row.get('outcome') is not None \
                and row['received'] < hi and row.get('result_day', 10 ** 9) < hi:
            return row
    raise AssertionError('样例缺少窗口单据')


def window_outcome_voids(records, lo, hi):
    return [{'key': row['key'], 'revision': row.get('revision', 1)} for row in records
            if lo <= row['day'] < hi and row.get('outcome') is not None
            and row['received'] < hi and row.get('result_day', 10 ** 9) < hi]


def fold_count(report, name):
    return next(row['单据'] for row in report['sections'][1]['records'] if row['时段'] == name)


@pytest.fixture(scope='module')
def dataset():
    return open_fixture()


@pytest.fixture(scope='module')
def base(dataset):
    return execute(dataset['records'], as_of=dataset['as_of'])


def test_void_train_outcome_recomputes_model_and_cross_zone_intervals(dataset, base):
    donor = window_member(dataset['records'], 0, 40)
    result = correct(dataset['records'], [{'key': donor['key'], 'revision': 1}], as_of=dataset['as_of'])
    note = result['correction']
    assert note['scope'] == 'MODEL_INVALIDATED' and note['status'] == 'ISSUED'
    assert note['base_receipt'] == base['run_id']
    assert note['corrected_receipt'] == result['run_id'] != base['run_id']
    assert result['feature_stamp'] != base['feature_stamp']
    before = {row['key']: row for row in base['rows']}
    changed_zones = {row['zone'] for row in result['rows'] if row['interval'] != before[row['key']]['interval']}
    assert len(changed_zones) >= 2
    register = [row for row in result['sections'][7]['records'] if row.get('登记') == '作废实绩版次']
    assert [row['单号'] for row in register] == [donor['key']]
    assert register[0]['所在窗口'] == '拟合' and register[0]['更正凭证'] == note['voucher']


def test_replay_only_void_updates_errors_and_keeps_dispatch(dataset, base):
    donor = window_member(dataset['records'], 65, 85)
    result = correct(dataset['records'], [{'key': donor['key'], 'revision': 1}], as_of=dataset['as_of'])
    note = result['correction']
    assert note['scope'] == 'REPLAY_ONLY' and note['status'] == 'ISSUED'
    assert result['rows'] == base['rows']
    assert result['feature_stamp'] == base['feature_stamp']
    assert result['performance'][0]['value'] == base['performance'][0]['value'] - 1
    assert result['run_id'] != base['run_id'] and note['corrected_receipt'] == result['run_id']


def test_replay_fully_voided_reports_undefined_metrics(dataset, base):
    voids = window_outcome_voids(dataset['records'], 65, 85)
    result = correct(dataset['records'], voids, as_of=dataset['as_of'])
    assert result['correction']['scope'] == 'REPLAY_ONLY'
    assert result['correction']['status'] == 'ISSUED'
    assert result['rows'] == base['rows']
    assert result['performance'] == [{'label': '回放实绩样本', 'value': 0},
                                     {'label': '回放绝对误差', 'value': None}]


def test_failed_correction_keeps_voucher_and_pauses_invalidated(dataset, base):
    voids = window_outcome_voids(dataset['records'], 43, 62)
    result = correct(dataset['records'], voids, as_of=dataset['as_of'])
    note = result['correction']
    assert note['scope'] == 'MODEL_INVALIDATED' and note['status'] == 'RETRY_REQUIRED'
    assert note['corrected_receipt'] is None
    assert note['base_receipt'] == base['run_id'] == result['run_id']
    paused = set(note['paused'])
    assert paused
    by_key = {row['key']: row for row in result['rows']}
    for key in paused:
        assert by_key[key]['state'] == '暂停' and by_key[key]['reason'] == 'CORRECTION_INVALIDATED'
    assert not any(row['state'] in ('已分派', '候补') for row in result['rows'])
    assert result['metrics'][-1]['value'] == result['capacity']


def test_wet_pause_survives_model_correction(dataset, base):
    wet = {row['key']: row for row in base['rows'] if row['state'] == '暂停'}
    assert wet
    donor = window_member(dataset['records'], 0, 40)
    result = correct(dataset['records'], [{'key': donor['key'], 'revision': 1}], as_of=dataset['as_of'])
    by_key = {row['key']: row for row in result['rows']}
    for key in wet:
        assert by_key[key]['state'] == '暂停' and by_key[key]['reason'] == 'WET_LOW_LIGHT'


def test_same_batch_rerun_issues_no_new_voucher(dataset):
    donor = window_member(dataset['records'], 0, 40)
    voids = [{'key': donor['key'], 'revision': 1}]
    first = correct(dataset['records'], voids, as_of=dataset['as_of'])
    second = correct(dataset['records'], list(reversed(voids)), as_of=dataset['as_of'])
    assert first['correction']['voucher'] == second['correction']['voucher']
    assert first['run_id'] == second['run_id']


def test_void_of_unknown_or_superseded_revision_is_noop(dataset, base):
    donor = window_member(dataset['records'], 0, 40)
    result = correct(dataset['records'], [{'key': donor['key'], 'revision': 999}], as_of=dataset['as_of'])
    assert result['correction']['scope'] == 'UNAFFECTED'
    assert result['rows'] == base['rows'] and result['run_id'] == base['run_id']
    assert result['correction']['corrected_receipt'] == base['run_id']


def test_late_outcome_cannot_reenter_closed_window(dataset, base):
    entries = [dict(row) for row in dataset['records']]
    donor = next(row for row in entries if row['key'] == window_member(dataset['records'], 0, 40)['key'])
    entries.append(dict(donor, revision=2, received=45, result_day=46, outcome=33.3))
    shifted = execute(entries, as_of=dataset['as_of'])
    assert fold_count(shifted, '拟合') == fold_count(base, '拟合') - 1
    result = correct(entries, [{'key': donor['key'], 'revision': 1}], as_of=dataset['as_of'])
    assert result['correction']['scope'] == 'UNAFFECTED'
    assert result['rows'] == shifted['rows']


@pytest.mark.parametrize('voids', [[], [{'key': 'LB-1'}], [{'key': 'LB-1', 'revision': 0}],
                                   [{'key': 'LB-1', 'revision': True}], ['LB-1'], [{'revision': 1}]])
def test_invalid_void_registration_rejected(dataset, voids):
    with pytest.raises(ValueError):
        correct(dataset['records'], voids, as_of=dataset['as_of'])
