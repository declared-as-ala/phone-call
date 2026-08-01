"""WebSocket `/ws`: admin JWT vs static bridge subscriber token."""

def test_ws_accepts_ws_broadcast_bridge_token(client, monkeypatch):
    bridge_token = "a" * 32
    monkeypatch.setattr(
        "app.config.WS_BROADCAST_BRIDGE_TOKEN",
        bridge_token,
        raising=False,
    )
    with client.websocket_connect(f"/ws?token={bridge_token}"):
        pass

