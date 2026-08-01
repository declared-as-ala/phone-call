from app.models import CallEvent, CallSession, TelephonyEventReceipt


def _index_names(table) -> set[str]:
    return {index.name for index in table.indexes}


def test_call_query_indexes_are_declared_in_metadata():
    assert "ix_call_events_session_id" in _index_names(CallEvent.__table__)
    assert "ix_call_sessions_status" in _index_names(CallSession.__table__)
    assert "ix_call_sessions_created_at" in _index_names(CallSession.__table__)


def test_telephony_receipt_provider_event_uniqueness_is_preserved():
    constraints = {constraint.name for constraint in TelephonyEventReceipt.__table__.constraints}
    assert "uq_telephony_event_receipt_provider_event" in constraints
