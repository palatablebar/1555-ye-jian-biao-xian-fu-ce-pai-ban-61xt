"""voided outcome correction."""

from .service import normalize_voids, locate_voids, decide_scope, issue_voucher

__all__ = ('normalize_voids', 'locate_voids', 'decide_scope', 'issue_voucher')
