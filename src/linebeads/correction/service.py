from collections.abc import Mapping
from hashlib import sha256
from unicodedata import normalize

from ..marking_evidence.service import compact
from .contracts import (CORRECTION_FORM, SCOPE_MODEL, SCOPE_NONE, SCOPE_REPLAY, STATUS_ISSUED,
                        CorrectionVoucher, VoidNotice, VoidRegistration)

WINDOW_NAMES = {'train': '拟合', 'calibration': '校准', 'replay': '回放', 'live': '当班',
                'excluded': '窗口隔离', 'superseded': '已被新版替代', 'unknown': '未入站'}
SCOPE_NOTES = {SCOPE_MODEL: '拟合或校准使用作废实绩，模型已停用，共用跨区区间一并重算',
               SCOPE_REPLAY: '仅回放实绩作废，已更新回放误差，工位照旧',
               SCOPE_NONE: '作废版次未参与拟合、校准或回放，当班处置不变'}
RETRY_NOTE = '模型失效且更正重算未完成，原凭证留查，失效部分暂停派工，请重试'


def normalize_voids(voids):
    if not isinstance(voids, (list, tuple)) or not voids:
        raise ValueError('作废登记应为非空序列')
    notices = set()
    for item in voids:
        if not isinstance(item, Mapping):
            raise ValueError('作废登记应为对象')
        key = item.get('key')
        revision = item.get('revision')
        if not isinstance(key, str):
            raise ValueError('作废登记缺少单号')
        key = normalize('NFKC', key).strip()
        if not key or len(key) > 64:
            raise ValueError('作废登记单号无效')
        if type(revision) is not int or not 1 <= revision <= 1000:
            raise ValueError('作废版次应为 1 到 1000 的整数')
        notices.add(VoidNotice(key, revision))
    return tuple(sorted(notices, key=lambda notice: (notice.key, notice.revision)))


def locate_voids(notices, intake, windows):
    latest = {record.key: record for record in intake.entries}
    placement = {}
    for name, records in windows.partitions():
        for record in records:
            placement[record.key] = name
    for key, _reason in windows.excluded:
        placement[key] = 'excluded'
    registrations = []
    for notice in notices:
        current = latest.get(notice.key)
        if current is None or notice.revision > current.revision:
            window = 'unknown'
        elif notice.revision < current.revision:
            window = 'superseded'
        else:
            window = placement.get(notice.key, 'unknown')
        registrations.append(VoidRegistration(notice.key, notice.revision, window))
    return tuple(registrations)


def decide_scope(registrations):
    windows = {registration.window for registration in registrations}
    if windows & {'train', 'calibration'}:
        return SCOPE_MODEL
    if 'replay' in windows:
        return SCOPE_REPLAY
    return SCOPE_NONE


def strip_voided_outcomes(documents, notices):
    targets = {(notice.key, notice.revision) for notice in notices}
    cleaned = []
    for document in documents:
        if isinstance(document, Mapping):
            key = document.get('key')
            key = normalize('NFKC', key).strip() if isinstance(key, str) else None
            if (key, document.get('revision', 1)) in targets and document.get('outcome') is not None:
                document = {**document, 'outcome': None, 'result_day': None, 'observed': True}
        cleaned.append(document)
    return cleaned


def issue_voucher(registrations, scope, status, base_receipt, corrected_receipt, paused, *,
                  capacity, mode, as_of):
    payload = {'form': CORRECTION_FORM, 'base': base_receipt, 'scope': scope, 'status': status,
               'voids': [(row.key, row.revision, row.window) for row in registrations],
               'corrected': corrected_receipt, 'paused': list(paused),
               'capacity': capacity, 'mode': mode, 'as_of': as_of}
    stamp = sha256(compact(payload).encode()).hexdigest()[4:20]
    return CorrectionVoucher(stamp, base_receipt, scope, status, tuple(registrations),
                             corrected_receipt, tuple(paused))


def correction_summary(voucher):
    note = SCOPE_NOTES[voucher.scope] if voucher.status == STATUS_ISSUED else RETRY_NOTE
    return {'voucher': voucher.stamp, 'status': voucher.status, 'scope': voucher.scope,
            'base_receipt': voucher.base_receipt, 'corrected_receipt': voucher.corrected_receipt,
            'voids': [{'key': row.key, 'revision': row.revision, 'window': row.window}
                      for row in voucher.voids],
            'paused': list(voucher.paused), 'note': note}


def registration_evidence(voucher):
    rows = [{'核对项': '本班更正凭证', '数量': voucher.stamp},
            {'核对项': '原凭证留查', '数量': voucher.base_receipt}]
    rows.extend({'单号': row.key, '作废版次': row.revision, '所在窗口': WINDOW_NAMES[row.window],
                 '登记': '作废实绩版次', '更正凭证': voucher.stamp} for row in voucher.voids)
    return rows
