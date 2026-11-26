from dataclasses import dataclass

CORRECTION_FORM = 'linebeads.correction.20261126.v1'

# 影响范围
SCOPE_MODEL = 'MODEL_INVALIDATED'
SCOPE_REPLAY = 'REPLAY_ONLY'
SCOPE_NONE = 'UNAFFECTED'

# 凭证状态
STATUS_ISSUED = 'ISSUED'
STATUS_RETRY = 'RETRY_REQUIRED'


@dataclass(frozen=True, slots=True)
class VoidNotice:
    key: str
    revision: int


@dataclass(frozen=True, slots=True)
class VoidRegistration:
    key: str
    revision: int
    window: str


@dataclass(frozen=True, slots=True)
class CorrectionVoucher:
    stamp: str
    base_receipt: str
    scope: str
    status: str
    voids: tuple[VoidRegistration, ...]
    corrected_receipt: str | None
    paused: tuple[str, ...]
