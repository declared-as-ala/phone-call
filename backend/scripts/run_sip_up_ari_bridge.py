#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sip_up_ari_bridge import SipUpAriBridge, SipUpAriBridgeConfig  # noqa: E402
from app.services.audio_convert import resolve_ffmpeg_executable  # noqa: E402


async def main() -> None:
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bridge = SipUpAriBridge(SipUpAriBridgeConfig.from_env())
    ffmpeg = resolve_ffmpeg_executable()
    if ffmpeg:
        logging.getLogger(__name__).info("IVR audio converter ready ffmpeg=%s", ffmpeg)
    else:
        logging.getLogger(__name__).warning(
            "IVR audio converter missing — calls may be silent. "
            "Run: pip install imageio-ffmpeg  (or install ffmpeg on PATH)"
        )
    logging.getLogger(__name__).warning(
        "ARI bridge standalone process pid=%s bridge_instance=%s — "
        "run only ONE instance per SIP UP Stasis app "
        "(ps aux | grep run_sip_up_ari_bridge | grep -v grep) "
        "to avoid duplicate IVR playback.",
        os.getpid(),
        bridge.bridge_instance_id,
    )
    await bridge.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
