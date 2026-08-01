import asyncio
import json
import logging
from unittest.mock import AsyncMock

from app.services.sip_up_ari_bridge import (
    SipUpAriBridge,
    SipUpAriBridgeConfig,
    SipUpAriEventMapper,
    _prepend_silence_pcm_wav_inplace,
    _read_prompt_initial_silence_ms,
    _read_prompt_preroll_ms,
    _read_spoken_min_lead_ms,
)


CALL_ID = "550e8400-e29b-41d4-a716-446655440000"


def _channel(channel_id="asterisk-channel-1", state="Up"):
    return {
        "id": channel_id,
        "name": "PJSIP/narayana-trunk-00000001",
        "state": state,
        "channelvars": {"CALL_ID": CALL_ID},
    }


def test_channel_state_ringing_maps_to_ringing_payload():
    mapper = SipUpAriEventMapper()

    payload = mapper.map_event(
        {
            "type": "ChannelStateChange",
            "timestamp": "2026-05-08T08:00:00Z",
            "channel": _channel(state="Ringing"),
        }
    )

    assert payload is not None
    assert payload["event_type"] == "RINGING"


def test_channel_state_ringing_is_idempotently_mapped_once_per_channel():
    mapper = SipUpAriEventMapper()
    event = {
        "type": "ChannelStateChange",
        "timestamp": "2026-05-08T08:00:00Z",
        "channel": _channel(state="Ringing"),
    }

    assert mapper.map_event(event)["event_type"] == "RINGING"
    assert mapper.map_event(event) is None


def test_channel_state_up_maps_to_answered_payload():
    mapper = SipUpAriEventMapper()

    payload = mapper.map_event(
        {
            "type": "ChannelStateChange",
            "timestamp": "2026-05-08T08:00:00Z",
            "channel": _channel(state="Up"),
        }
    )

    assert payload["provider"] == "sip_up"
    assert payload["provider_call_id"] == "asterisk-channel-1"
    assert payload["call_id"] == CALL_ID
    assert payload["event_type"] == "ANSWERED"
    assert payload["provider_event_id"].startswith("ari-")
    assert "digit" not in payload


def test_channel_state_up_is_idempotently_mapped_once_per_channel():
    mapper = SipUpAriEventMapper()
    event = {
        "type": "ChannelStateChange",
        "timestamp": "2026-05-08T08:00:00Z",
        "channel": _channel(state="Up"),
    }

    assert mapper.map_event(event)["event_type"] == "ANSWERED"
    assert mapper.map_event(event) is None


def test_mapper_resolve_repairs_backward_only_channel_mapping():
    """If call_channels UUID→ARI channel exists but channel_call_ids is stale, sync forward."""
    mapper = SipUpAriEventMapper()
    ch = "asterisk-channel-fw-miss"
    mapper.call_channels[CALL_ID] = ch
    assert mapper.channel_call_ids.get(ch) is None
    assert mapper.resolve_call_id_for_channel(ch) == CALL_ID
    assert mapper.channel_call_ids[ch] == CALL_ID


def test_iv_merge_stale_chan_scope_into_uuid_buckets():
    """First play scoped @chan:X then real CALL_ID — union lanes so replay stays deduped."""
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )
    ch = "chan-scope-merge"
    lane = bridge._spoken_body_playback_lane("Say this once.", "k")
    stale = f"@chan:{ch}"
    bridge._ivr_play_once_by_call[stale] = {lane}
    assert bridge._try_begin_playback_once(CALL_ID, ch, lane) is False
    assert stale not in bridge._ivr_play_once_by_call
    assert lane in bridge._ivr_play_once_by_call[CALL_ID]


def test_duplicate_answered_enqueues_iv_playback_only_once(monkeypatch):
    """Two ANSWERED webhook→IVR dispatches must not enqueue two background playback tasks."""
    import app.services.sip_up_ari_bridge as bridge_mod

    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
    )
    bridge = SipUpAriBridge(config)

    monkeypatch.setattr(
        bridge,
        "_post_backend_event",
        lambda _p: {
            "simulator_step": "consent",
            "ivr_speech": {"prompt_key": "consent_prompt", "text": "Say this once"},
        },
    )
    monkeypatch.setattr(bridge, "_answer_channel", lambda *_a, **_k: True)
    monkeypatch.setattr(bridge, "_stop_channel_media_sync", lambda *_a, **_k: None)

    spoken = AsyncMock()
    monkeypatch.setattr(SipUpAriBridge, "apply_spoken_prompt", spoken)

    ctr = {"i": 0}

    def force_answered(_event, *, call_id_override=None):
        ctr["i"] += 1
        return {
            "provider": "sip_up",
            "provider_call_id": "ch-dup-ans",
            "provider_event_id": f"dup-{ctr['i']}",
            "call_id": CALL_ID,
            "event_type": "ANSWERED",
            "raw_payload": {},
        }

    monkeypatch.setattr(bridge.mapper, "map_event", force_answered)

    created_tasks: list = []
    orig_ct = asyncio.create_task

    def capture_task(coro):
        task = orig_ct(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(bridge_mod.asyncio, "create_task", capture_task)

    msg = json.dumps({"type": "ChannelStateChange", "channel": _channel(channel_id="ch-dup-ans")})

    async def run():
        await bridge.handle_raw_message(msg)
        await bridge.handle_raw_message(msg)
        for t in created_tasks:
            await t

    asyncio.run(run())

    assert len(created_tasks) == 1
    assert spoken.await_count == 1


def test_handle_backend_ws_nested_call_answered_skips_ivr(monkeypatch):
    """call_event wrapping CALL_ANSWERED + ivr_speech must not replay (webhook is canonical)."""
    spoken = AsyncMock()
    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
    )
    bridge = SipUpAriBridge(config)
    bridge.mapper.remember_call_id("chan-nested", CALL_ID)
    monkeypatch.setattr(SipUpAriBridge, "apply_spoken_prompt", spoken)
    monkeypatch.setattr(SipUpAriBridge, "apply_prompt_action", AsyncMock())

    asyncio.run(
        bridge.handle_backend_ws_broadcast(
            {
                "type": "call_event",
                "event": {
                    "id": 8844,
                    "session_id": CALL_ID,
                    "event_type": "CALL_ANSWERED",
                    "message": "answered",
                    "created_at": "2026-05-09T12:00:00Z",
                },
                "ivr_speech": {"prompt_key": "consent_prompt", "text": "Should not replay"},
            }
        )
    )
    spoken.assert_not_awaited()


def test_dtmf_maps_to_dtmf_payload_and_reuses_remembered_call_id():
    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("asterisk-channel-1", CALL_ID)

    payload = mapper.map_event(
        {
            "type": "ChannelDtmfReceived",
            "timestamp": "2026-05-08T08:00:01Z",
            "channel": {"id": "asterisk-channel-1", "state": "Up"},
            "digit": "1",
        }
    )

    assert payload["call_id"] == CALL_ID
    assert payload["event_type"] == "DTMF"
    assert payload["digit"] == "1"


def test_hangup_and_stasis_end_map_to_hangup_once():
    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("asterisk-channel-1", CALL_ID)

    hangup = mapper.map_event(
        {
            "type": "ChannelHangupRequest",
            "timestamp": "2026-05-08T08:00:02Z",
            "channel": {"id": "asterisk-channel-1"},
        }
    )
    duplicate = mapper.map_event(
        {
            "type": "StasisEnd",
            "timestamp": "2026-05-08T08:00:03Z",
            "channel": {"id": "asterisk-channel-1"},
        }
    )

    assert hangup["event_type"] == "HANGUP"
    assert duplicate is None


def test_failed_dial_maps_to_failed_payload():
    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("asterisk-channel-1", CALL_ID)

    payload = mapper.map_event(
        {
            "type": "Dial",
            "timestamp": "2026-05-08T08:00:04Z",
            "channel": {"id": "asterisk-channel-1"},
            "dialstatus": "CHANUNAVAIL",
        }
    )

    assert payload["event_type"] == "FAILED"


def test_stasis_start_can_extract_call_id_from_args():
    mapper = SipUpAriEventMapper()

    payload = mapper.map_event(
        {
            "type": "StasisStart",
            "timestamp": "2026-05-08T08:00:05Z",
            "channel": {"id": "asterisk-channel-2", "state": "Up"},
            "args": [CALL_ID],
        }
    )

    assert payload["event_type"] == "ANSWERED"
    assert payload["call_id"] == CALL_ID


def test_bridge_posts_mapped_payload_to_backend(monkeypatch):
    posted = []
    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
    )
    bridge = SipUpAriBridge(config)

    def fake_post(payload):
        posted.append(payload)
        return {"simulator_step": "verification_code", "session_status": "collecting"}

    monkeypatch.setattr(bridge, "_post_backend_event", fake_post)
    monkeypatch.setattr(bridge, "_play_prompt_blocking", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_hangup_channel", lambda *args: None)

    result = asyncio.run(
        bridge.handle_raw_message(
            json.dumps(
                {
                    "type": "ChannelDtmfReceived",
                    "timestamp": "2026-05-08T08:00:06Z",
                    "channel": _channel(),
                    "digit": "7",
                }
            )
        )
    )

    assert result["event_type"] == "DTMF"
    assert posted == [result]


def test_bridge_selects_prompts_from_backend_event_results():
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )

    assert bridge.prompt_for_backend_result(
        payload={"event_type": "ANSWERED"},
        backend_response={"simulator_step": "consent"},
    ) == ("consent", False)
    assert bridge.prompt_for_backend_result(
        payload={"event_type": "DTMF", "digit": "1"},
        backend_response={"simulator_step": "verification_code"},
    ) == (None, False)
    assert bridge.prompt_for_backend_result(
        payload={"event_type": "DTMF", "digit": "1"},
        backend_response={"simulator_step": "waiting_admin_code_send"},
    ) == ("admin_instruction", False)
    assert bridge.prompt_for_backend_result(
        payload={"event_type": "DTMF", "digit": "9"},
        backend_response={
            "simulator_step": "verification_code",
            "detail": "pending_admin_verification",
        },
    ) == ("pending_admin", False)
    assert bridge.prompt_for_backend_result(
        payload={"event_type": "DTMF", "digit": "2"},
        backend_response={"simulator_step": "waiting_admin_code_send"},
    ) == ("admin_instruction", False)
    assert bridge.prompt_for_backend_result(
        payload={"event_type": "DTMF", "digit": "6"},
        backend_response={"detail": "pending_admin_verification"},
    ) == ("pending_admin", False)


def test_bridge_selects_prompts_from_admin_websocket_events():
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )

    assert bridge.prompt_for_backend_ws_event({"event_type": "ADMIN_CODE_SENT_CONFIRMED"}) == ("code_sent", False)
    assert bridge.prompt_for_backend_ws_event({"event_type": "ADMIN_VERIFICATION_APPROVED"}) == ("approved", True)
    assert bridge.prompt_for_backend_ws_event({"event_type": "ADMIN_VERIFICATION_REJECTED", "message": "try again"}) == (
        "rejected",
        False,
    )
    assert bridge.prompt_for_backend_ws_event(
        {"event_type": "ADMIN_VERIFICATION_REJECTED", "message": "maximum attempts reached"}
    ) == ("declined", True)
    assert bridge.prompt_for_backend_ws_event({"event_type": "VERIFICATION_SUCCESS"}) == (None, False)


def test_ws_duplicate_prompt_detection_per_event_id():
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )
    call_id = "550e8400-e29b-41d4-a716-446655440000"
    ev = {"id": "evt-1", "event_type": "ADMIN_CODE_SENT_CONFIRMED", "session_id": call_id}
    ivr = {"speech_script_key": "code_sent_prompt", "text": "x"}
    assert bridge._ws_prompt_is_duplicate(call_id, "ADMIN_CODE_SENT_CONFIRMED", ev, ivr) is False
    assert bridge._ws_prompt_is_duplicate(call_id, "ADMIN_CODE_SENT_CONFIRMED", ev, ivr) is True


def test_ws_admin_code_sent_deduped_once_per_call_even_with_second_event_row():
    """Double-submit races can persist two ADMIN_CODE_SENT rows; callee must not hear prompt twice."""
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )
    call_id = "550e8400-e29b-41d4-a716-446655440001"
    ev1 = {"id": "evt-10", "event_type": "ADMIN_CODE_SENT_CONFIRMED", "session_id": call_id}
    ev2 = {"id": "evt-11", "event_type": "ADMIN_CODE_SENT_CONFIRMED", "session_id": call_id}
    ivr = {"speech_script_key": "code_sent_prompt", "text": "x"}
    assert bridge._ws_prompt_is_duplicate(call_id, "ADMIN_CODE_SENT_CONFIRMED", ev1, ivr) is False
    assert bridge._ws_prompt_is_duplicate(call_id, "ADMIN_CODE_SENT_CONFIRMED", ev2, ivr) is True


def test_answered_spawns_background_play_with_preroll_sleep(monkeypatch):
    import app.services.sip_up_ari_bridge as ab_mod

    preroll_secs = []

    async def spy_sleep(seconds: float):
        preroll_secs.append(seconds)

    monkeypatch.setenv("IVR_POST_ANSWER_RTP_SETTLE_MS", "0")

    async def spy_sleep(seconds: float):
        preroll_secs.append(seconds)

    monkeypatch.setattr(ab_mod.asyncio, "sleep", spy_sleep)

    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
        prompt_preroll_ms=822,
    )
    bridge = SipUpAriBridge(config)

    def fake_post(_payload):
        return {
            "simulator_step": "consent",
            "ivr_speech": {"prompt_key": "consent_prompt", "text": "Hello there"},
        }

    monkeypatch.setattr(bridge, "_post_backend_event", fake_post)
    monkeypatch.setattr(bridge, "_tts_or_static_prompt_blocking", lambda *a, **k: None)
    monkeypatch.setattr(bridge, "_answer_channel", lambda *_a, **_k: True)

    spawned = []
    real_ct = asyncio.create_task

    def capture_task(coro):
        task = real_ct(coro)
        spawned.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", capture_task)

    async def arun():
        await bridge.handle_raw_message(
            json.dumps(
                {
                    "type": "ChannelStateChange",
                    "timestamp": "2026-05-08T08:00:00Z",
                    "channel": {
                        "id": "chan-v",
                        "state": "Up",
                        "channelvars": {"CALL_ID": CALL_ID},
                    },
                }
            )
        )
        if spawned:
            await asyncio.gather(*spawned)

    asyncio.run(arun())

    assert spawned
    assert preroll_secs
    assert abs(preroll_secs[0] - (822 / 1000.0)) < 1e-6


def test_play_missing_playback_id_does_not_raise(monkeypatch):
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )
    monkeypatch.setattr(bridge, "_playback_rest_start", lambda *_a, **_k: None)
    bridge._play_media_string_wait("chan-x", "sound:ivr/consent", "consent_prompt", anchor_gen_snapshot=0)


def test_read_prompt_preroll_ms_defaults_to_200(monkeypatch):
    monkeypatch.delenv("ASTERISK_PROMPT_PREROLL_MS", raising=False)
    assert _read_prompt_preroll_ms() == 200


def test_read_prompt_initial_silence_ms_defaults(monkeypatch):
    monkeypatch.delenv("ASTERISK_PROMPT_INITIAL_SILENCE_MS", raising=False)
    assert _read_prompt_initial_silence_ms() == 700


def test_read_spoken_min_lead_ms_defaults(monkeypatch):
    monkeypatch.delenv("ASTERISK_SPOKEN_MIN_LEAD_MS", raising=False)
    assert _read_spoken_min_lead_ms() == 380


def test_ws_broadcast_skips_telephony_canonical_prompt_fanout(monkeypatch):
    """Consent / recipient prompts are played from webhook response; WS must not replay them."""

    spoken: list[str] = []

    async def spy_apply_spoken(self, *_, **__) -> None:
        spoken.append("spoken")

    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
    )
    bridge = SipUpAriBridge(config)
    bridge.mapper.remember_call_id("chan-live", CALL_ID)
    monkeypatch.setattr(SipUpAriBridge, "apply_spoken_prompt", spy_apply_spoken)
    monkeypatch.setattr(SipUpAriBridge, "apply_prompt_action", spy_apply_spoken)

    async def run():
        await bridge.handle_backend_ws_broadcast(
            {
                "type": "CALL_ANSWERED",
                "event": {
                    "id": 991,
                    "session_id": CALL_ID,
                    "event_type": "CALL_ANSWERED",
                    "message": "test",
                    "created_at": "2026-05-09T12:00:00Z",
                },
                "ivr_speech": {
                    "prompt_key": "consent_prompt",
                    "text": "Please press one or two",
                },
            }
        )

    asyncio.run(run())
    assert spoken == []


def test_prepend_silence_pcm_wav_adds_seconds(tmp_path, monkeypatch):
    import wave as wave_mod

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "one.wav"
    with wave_mod.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\xff\x00" * 1600)

    orig = wave_mod.open(str(path), "rb").getnframes()
    _prepend_silence_pcm_wav_inplace(str(path), 500)
    with wave_mod.open(str(path), "rb") as w:
        new = w.getnframes()

    assert new == orig + 4000


def test_apply_spoken_prompt_passes_config_prepend_to_tts(monkeypatch):
    captured: dict[str, int] = {}

    def spy_tts(
        self,
        channel_id: str,
        fallback_key: str,
        text: str,
        prompt_key_for_log: str,
        *,
        anchor_gen_snapshot: int,
        prepend_silence_ms: int = 0,
        prefer_static_if_cold: bool = False,
    ) -> None:
        captured["prepend_silence_ms"] = prepend_silence_ms
        captured["prefer_static_if_cold"] = prefer_static_if_cold

    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
        prompt_initial_silence_ms=612,
        prompt_preroll_ms=200,
    )
    bridge = SipUpAriBridge(config)
    monkeypatch.setattr(SipUpAriBridge, "_tts_or_static_prompt_blocking", spy_tts)
    monkeypatch.setattr(bridge, "_answer_channel", lambda *_a, **_k: True)

    async def noop_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    async def run():
        await bridge.apply_spoken_prompt(
            "chan-a",
            "consent",
            "Hello tester",
            False,
            preroll_ms=300,
            log_prompt_key="consent",
        )

    asyncio.run(run())

    assert captured["prepend_silence_ms"] == 612
    assert captured["prefer_static_if_cold"] is True


def test_dtmf_barge_in_runs_before_backend_post(monkeypatch):
    seq = []

    def fake_interrupt(self, channel_id: str, *, reason: str) -> None:
        seq.append("barge")

    def fake_post(_payload):
        seq.append("post")
        return {"simulator_step": "verification_code"}

    async def noop_play(*_a, **_k):
        seq.append("play")

    config = SipUpAriBridgeConfig(
        host="127.0.0.1",
        port=8088,
        username="ari-user",
        password="secret-not-logged",
        backend_events_url="http://backend.test/api/telephony/events",
    )
    bridge = SipUpAriBridge(config)

    monkeypatch.setattr(SipUpAriBridge, "_interrupt_playback_barge_in_sync", fake_interrupt)
    monkeypatch.setattr(bridge, "_post_backend_event", fake_post)
    monkeypatch.setattr(bridge, "apply_prompt_action", noop_play)

    async def run():
        await bridge.handle_raw_message(
            json.dumps(
                {
                    "type": "ChannelDtmfReceived",
                    "timestamp": "2026-05-08T08:00:06Z",
                    "channel": _channel(),
                    "digit": "5",
                }
            )
        )

    asyncio.run(run())

    assert seq[:2] == ["barge", "post"]


def test_handle_backend_ws_broadcast_admin_code_sent_plays_prompt_once(monkeypatch):
    """Second ADMIN websocket message must not replay code_sent_prompt (one-shot per call)."""
    spoken = AsyncMock()
    monkeypatch.delenv("ASTERISK_ADMIN_CODE_SENT_AUDIO_MODE", raising=False)

    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("chan-ivr", CALL_ID)
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        ),
        mapper=mapper,
    )
    monkeypatch.setattr(bridge, "_interrupt_playback_barge_in_sync", lambda *_a, **_k: None)
    monkeypatch.setattr(bridge, "apply_spoken_prompt", spoken)
    monkeypatch.setattr(bridge, "apply_prompt_action", AsyncMock())
    monkeypatch.setattr(bridge, "_finalize_terminal_hangup", AsyncMock())

    base_event = {
        "id": 101,
        "session_id": CALL_ID,
        "event_type": "ADMIN_CODE_SENT_CONFIRMED",
        "message": "ok",
        "created_at": "2026-01-01T00:00:00Z",
        "actor_type": "admin",
    }

    payload = {
        "type": "ADMIN_CODE_SENT_CONFIRMED",
        "event": dict(base_event),
        "ivr_speech": {
            "prompt_key": "code_sent",
            "speech_script_key": "code_sent_prompt",
            "text": "six digit entry",
        },
    }

    async def run():
        await bridge.handle_backend_ws_broadcast(dict(payload))
        payload2 = {
            **payload,
            "event": {**base_event, "id": 102},
        }
        await bridge.handle_backend_ws_broadcast(payload2)

    asyncio.run(run())
    assert spoken.await_count == 1


def test_handle_backend_ws_approve_plays_once_even_with_second_event_row(monkeypatch):
    """Two ADMIN_APPROVED websocket deliveries must not replay the approved prompt."""

    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("chan-ap", CALL_ID)

    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        ),
        mapper=mapper,
    )
    monkeypatch.setattr(bridge, "_interrupt_playback_barge_in_sync", lambda *_a, **_k: None)

    plays = []

    async def spy_apply_prompt(self, *args, **kwargs):
        plays.append("apply_prompt_action")

    monkeypatch.setattr(SipUpAriBridge, "apply_prompt_action", spy_apply_prompt)
    monkeypatch.setattr(SipUpAriBridge, "apply_spoken_prompt", AsyncMock())
    monkeypatch.setattr(SipUpAriBridge, "_finalize_terminal_hangup", AsyncMock())

    base_event = {
        "id": 901,
        "session_id": CALL_ID,
        "event_type": "ADMIN_VERIFICATION_APPROVED",
        "message": "ok",
        "created_at": "2026-05-09T12:00:00Z",
        "actor_type": "admin",
    }
    envelope = {"type": "ADMIN_VERIFICATION_APPROVED", "event": dict(base_event)}

    async def run():
        await bridge.handle_backend_ws_broadcast(dict(envelope))
        await bridge.handle_backend_ws_broadcast(
            {"type": "ADMIN_VERIFICATION_APPROVED", "event": {**base_event, "id": 902}}
        )

    asyncio.run(run())
    assert len(plays) == 1


def test_apply_spoken_prompt_skipped_second_time_same_normalized_body(monkeypatch):
    """Identical scrubbed wording must not replay (even if callers pass differing prompt keys).

    Dedupe fingerprint is normalized text, not speech_script_key.
    """
    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("lane-ch", CALL_ID)

    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
            backend_events_url="http://backend.test/api/telephony/events",
        ),
        mapper=mapper,
    )
    monkeypatch.setattr(bridge, "_answer_channel", lambda *_a, **_k: True)
    monkeypatch.setattr(bridge, "_stop_channel_media_sync", lambda *_a, **_k: None)

    tts_calls: list[int] = []

    def spy_tts(
        self,
        channel_id: str,
        fallback_key: str,
        text: str,
        prompt_key_for_log: str,
        *,
        anchor_gen_snapshot: int,
        prepend_silence_ms: int = 0,
        prefer_static_if_cold: bool = False,
    ) -> None:
        tts_calls.append(1)

    monkeypatch.setattr(SipUpAriBridge, "_tts_or_static_prompt_blocking", spy_tts)

    async def noop_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    utterance = "Please press option one."

    async def run():
        await bridge.apply_spoken_prompt(
            "lane-ch",
            "k-a",
            utterance,
            False,
            preroll_ms=0,
            log_prompt_key="k-a",
            speech_script_key="consent_prompt",
        )
        await bridge.apply_spoken_prompt(
            "lane-ch",
            "k-b",
            utterance,
            False,
            preroll_ms=0,
            log_prompt_key="k-b",
            speech_script_key="consent_prompt",
        )

    asyncio.run(run())
    assert len(tts_calls) == 1


def test_handle_backend_ws_broadcast_missing_channel_logs_error(monkeypatch, caplog):
    monkeypatch.delenv("ASTERISK_ADMIN_CODE_SENT_AUDIO_MODE", raising=False)
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        ),
        mapper=SipUpAriEventMapper(),
    )
    caplog.set_level(logging.ERROR)

    payload = {
        "type": "ADMIN_CODE_SENT_CONFIRMED",
        "event": {
            "id": 1,
            "session_id": CALL_ID,
            "event_type": "ADMIN_CODE_SENT_CONFIRMED",
            "message": "ok",
            "created_at": "2026-01-01T00:00:00Z",
            "actor_type": "admin",
        },
        "ivr_speech": {"text": "x"},
    }

    asyncio.run(bridge.handle_backend_ws_broadcast(payload))
    assert any("No active channel for code_sent_prompt" in r.message for r in caplog.records)


def test_handle_backend_ws_call_hangup_tears_down_channel(monkeypatch):
    """Dashboard end-call must DELETE the live ARI channel (not leave Stasis orphaned)."""
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        ),
        mapper=SipUpAriEventMapper(),
    )
    bridge.mapper.remember_call_id("chan-hangup-1", CALL_ID)
    hung: list[str] = []

    def _fake_hangup(channel_id: str) -> None:
        hung.append(channel_id)

    monkeypatch.setattr(bridge, "_hangup_channel", _fake_hangup)
    monkeypatch.setattr(bridge, "_interrupt_playback_barge_in_sync", lambda *a, **k: None)

    async def run() -> None:
        await bridge.handle_backend_ws_broadcast(
            {
                "type": "CALL_HANGUP",
                "event": {
                    "id": 99,
                    "session_id": CALL_ID,
                    "event_type": "CALL_HANGUP",
                    "message": "Call ended by operator",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
        )

    asyncio.run(run())
    assert hung == ["chan-hangup-1"]


def test_apply_prompt_action_terminal_hangup_after_playback_finishes(monkeypatch):
    """Declined-style terminal media prompts must hang up only after `_play_prompt_blocking` returns."""
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        )
    )
    seq: list = []
    monkeypatch.setattr(bridge, "_answer_channel", lambda *_a, **_k: True)
    monkeypatch.setattr(bridge, "_play_prompt_blocking", lambda *_a, **_k: seq.append("play_blocking"))

    async def fake_finalize(_ch, _k, mono):
        seq.append(("finalize", mono is not None))

    monkeypatch.setattr(bridge, "_finalize_terminal_hangup", fake_finalize)

    async def run():
        await bridge.apply_prompt_action("chan-decline", "declined", True)

    asyncio.run(run())
    assert seq == ["play_blocking", ("finalize", True)]


def test_handle_backend_ws_broadcast_no_event_is_noop():
    mapper = SipUpAriEventMapper()
    mapper.remember_call_id("chan-ivr", CALL_ID)
    bridge = SipUpAriBridge(
        SipUpAriBridgeConfig(
            host="127.0.0.1",
            port=8088,
            username="ari-user",
            password="secret-not-logged",
        ),
        mapper=mapper,
    )
    asyncio.run(bridge.handle_backend_ws_broadcast({"type": "session_update"}))
