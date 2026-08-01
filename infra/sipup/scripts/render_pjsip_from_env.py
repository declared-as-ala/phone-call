#!/usr/bin/env python3
"""Fill REPLACE_* in ``config/pjsip.conf.template`` → ``config/pjsip.conf`` using ``infra/sipup/.env``.

Run from repo root: ``python3 infra/sipup/scripts/render_pjsip_from_env.py``
Or: ``cd infra/sipup && python3 scripts/render_pjsip_from_env.py``

Also invoked automatically by ``docker compose up`` via the ``pjsip-render`` init service.

Keep the generated ``pjsip.conf`` out of version control (see ``infra/sipup/.gitignore``).
"""
from __future__ import annotations

import re
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_SIPUP_REGISTRAR = "sip.sipup.org"
DEFAULT_SIPUP_PORT = "5060"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_external_ip(env: dict[str, str]) -> str:
    ip = env.get("ASTERISK_EXTERNAL_IP", "").strip()
    if ip:
        return ip
    # Try fetching public IP
    for url in ("https://ifconfig.me/ip", "https://ipinfo.io/ip", "https://api.ipify.org"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
            with urllib.request.urlopen(req, timeout=5) as r:
                res = r.read().decode("utf-8").strip()
                if res:
                    return res
        except Exception:
            continue
    raise SystemExit("Could not resolve external IP address. Set ASTERISK_EXTERNAL_IP in .env.")


def sipup_registrar(env: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    host = (env.get("SIPUP_SIP_HOST") or "").strip()
    domain = (env.get("SIPUP_SIP_DOMAIN") or "").strip()
    registrar = host or domain or DEFAULT_SIPUP_REGISTRAR
    port_raw = (env.get("SIPUP_SIP_PORT") or DEFAULT_SIPUP_PORT).strip()
    port = port_raw if port_raw.isdigit() else DEFAULT_SIPUP_PORT
    from_domain = domain or registrar
    username = (env.get("SIPUP_SIP_USERNAME") or "").strip()
    aor_contact = f"sip:{registrar}:{port}"
    server_uri = f"sip:{registrar}:{port}"
    client_uri = f"sip:{username}@{from_domain}" if username else f"sip:{from_domain}"
    return aor_contact, registrar, from_domain, port, server_uri, client_uri


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    template_path = root / "config" / "pjsip.conf.template"
    out_path = root / "config" / "pjsip.conf"
    rtp_template_path = root / "config" / "rtp.conf.template"
    rtp_out_path = root / "config" / "rtp.conf"

    if not env_path.is_file():
        raise SystemExit(f"Missing {env_path} (copy from .env.example and fill secrets).")
    if not template_path.is_file():
        raise SystemExit(f"Missing {template_path}")
    env = load_env(env_path)
    external_ip = get_external_ip(env)

    # Render rtp.conf
    if rtp_template_path.is_file():
        rtp_text = rtp_template_path.read_text(encoding="utf-8")
        rtp_text = rtp_text.replace("REPLACE_ASTERISK_EXTERNAL_IP", external_ip)
        rtp_out_path.write_text(rtp_text, encoding="utf-8")
        print(f"Wrote {rtp_out_path} (externaddr={external_ip})")

    aor_contact, identify_match, from_domain, _port, server_uri, client_uri = sipup_registrar(env)
    sipup_dtmf_mode = (env.get("SIPUP_DTMF_MODE") or "rfc4733").strip() or "rfc4733"
    replacements = {
        "REPLACE_ASTERISK_EXTERNAL_IP": external_ip,
        "REPLACE_SIPUP_DTMF_MODE": sipup_dtmf_mode,
        "REPLACE_SIP_USER": env.get("ASTERISK_SIP_USER") or env.get("SOFTPHONE_SIP_USER") or "softphone1",
        "REPLACE_SIP_PASSWORD": env.get("ASTERISK_SIP_PASSWORD") or env.get("SOFTPHONE_SIP_PASSWORD") or "changeme-softphone",
        "REPLACE_SIPUP_SIP_USERNAME": env.get("SIPUP_SIP_USERNAME", ""),
        "REPLACE_SIPUP_SIP_PASSWORD": env.get("SIPUP_SIP_PASSWORD", ""),
        "REPLACE_SIPUP_OUTBOUND_CALLER_ID": env.get("SIPUP_OUTBOUND_CALLER_ID", ""),
        "REPLACE_SIPUP_AOR_CONTACT": aor_contact,
        "REPLACE_SIPUP_IDENTIFY_MATCH": identify_match,
        "REPLACE_SIPUP_FROM_DOMAIN": from_domain,
        "REPLACE_SIPUP_SERVER_URI": server_uri,
        "REPLACE_SIPUP_CLIENT_URI": client_uri,
    }
    text = template_path.read_text(encoding="utf-8")
    text_out = text
    for needle, inject in replacements.items():
        text_out = text_out.replace(needle, inject)
    out_path.write_text(text_out, encoding="utf-8")

    leftover = [
        line.strip()
        for line in text_out.splitlines()
        if re.search(r"^[^;]*REPLACE_[A-Z0-9_]+", line)
    ]
    if leftover:
        raise SystemExit(
            "Some placeholders were not replaced (missing vars in .env?): "
            + "; ".join(leftover[:5])
        )
    print(
        f"Wrote {out_path} from {template_path} + {env_path} "
        f"(SIP UP contact={aor_contact} external_ip={external_ip})"
    )


if __name__ == "__main__":
    main()
