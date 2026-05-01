from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from manager_engine import analyze_symbol_manager, save_bridge_market_data
from manager_journal import add_trade_review, summary as manager_summary
from mt5_execution import execute_signal, list_candidates
from mt5_signals import build_live_signal_pack
from screenshot_analyzer import analyze_chart_screenshot
from signal_learning import evaluate_pending_signals
from llm_provider import load_llm_settings
from core.storage import init_audit_schema, write_audit
from simple_agent import (
    close_trade as simple_close_trade,
    execute_trade_on_mt5 as simple_execute_trade_on_mt5,
    list_trades as simple_list_trades,
    open_trade as simple_open_trade,
    run_strategy_cycle as simple_run_strategy_cycle,
    strategy_status as simple_strategy_status,
    sync_trades as simple_sync_trades,
)

load_dotenv('.env')

app = FastAPI(title="Trading Agent Mobile API", version="1.5.0", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent
LIVE_DIR = ROOT / "knowledge" / "live"
SCREEN_DIR = LIVE_DIR / "screenshots"
DASHBOARD_FILE = ROOT / "web" / "dashboard.html"
DESKTOP_SIMPLE_FILE = ROOT / "web" / "desktop_simple.html"
ADMIN_DASHBOARD_FILE = ROOT / "web" / "desktop_admin.html"
JOURNAL_FILE = LIVE_DIR / "mt5_signal_journal.jsonl"
METRICS_FILE = LIVE_DIR / "training_metrics.json"
LOG_FILE = LIVE_DIR / "training_runtime.log"
SIGNALS_FILE = LIVE_DIR / "mt5_live_signals.json"
AGENT_INTEL_FILE = LIVE_DIR / "agent_intel.json"
PROFIT_MODE_STATE_FILE = LIVE_DIR / "profit_mode_state.json"
ACCESS_STATE_FILE = LIVE_DIR / "access_state.json"
REQUEST_AUTHORIZATION: ContextVar[str] = ContextVar("request_authorization", default="")
ACCESS_LOCK = threading.Lock()
PUBLIC_PATHS = {"/health", "/version", "/", "/dashboard", "/desktop", "/admin", "/changelog", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}



def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _mask_token(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:3] + "..."
    return value[:6] + "..." + value[-4:]
def _degraded_mt5_response(action: str, exc: Exception) -> dict:
    return {
        "ok": False,
        "status": "degraded",
        "action": action,
        "message": str(exc),
        "hint": "Verifier MT5 (terminal ouvert + compte connecte + credentials valides).",
    }


def _configured_api_token() -> str:
    return (os.getenv("API_TOKEN") or os.getenv("MOBILE_DASH_TOKEN") or "").strip()


def _configured_admin_token() -> str:
    return (os.getenv("ADMIN_DASH_TOKEN") or os.getenv("API_TOKEN") or os.getenv("MOBILE_DASH_TOKEN") or "").strip()


def _extract_header_token() -> str:
    auth = (REQUEST_AUTHORIZATION.get() or "").strip()
    if not auth:
        return ""
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return auth


def _load_access_state() -> dict:
    data = _read_json(ACCESS_STATE_FILE)
    if not isinstance(data, dict):
        data = {}
    requests = data.get("requests")
    sessions = data.get("sessions")
    if not isinstance(requests, list):
        requests = []
    if not isinstance(sessions, list):
        sessions = []
    state = {"requests": requests, "sessions": sessions}
    _cleanup_access_state_locked(state)
    return state


def _save_access_state(state: dict) -> None:
    _write_json(ACCESS_STATE_FILE, state)


def _cleanup_access_state_locked(state: dict) -> None:
    now = _utc_now()

    for sess in state.get("sessions", []):
        if not isinstance(sess, dict):
            continue
        if not bool(sess.get("active", True)):
            continue
        expires_at = _parse_iso(sess.get("expires_at"))
        if expires_at and now >= expires_at:
            sess["active"] = False
            sess["revoked_at"] = _utc_now_iso()
            sess["revoked_reason"] = "expired"

    stale_after = now - timedelta(hours=48)
    for req in state.get("requests", []):
        if not isinstance(req, dict):
            continue
        if str(req.get("status", "")).upper() != "PENDING":
            continue
        created_at = _parse_iso(req.get("created_at"))
        if created_at and created_at < stale_after:
            req["status"] = "EXPIRED"
            req["updated_at"] = _utc_now_iso()
            req["note"] = req.get("note") or "Demande expiree automatiquement"


def _session_is_active(session: dict) -> bool:
    if not bool(session.get("active", False)):
        return False
    expires_at = _parse_iso(session.get("expires_at"))
    if expires_at and _utc_now() >= expires_at:
        return False
    return True


def _find_request(state: dict, request_id: str) -> Optional[dict]:
    for req in state.get("requests", []):
        if str(req.get("id")) == request_id:
            return req
    return None


def _find_session_by_request(state: dict, request_id: str) -> Optional[dict]:
    for sess in state.get("sessions", []):
        if str(sess.get("request_id")) == request_id and _session_is_active(sess):
            return sess
    return None


def _find_active_session_for_device(state: dict, account_name: str, device_id: str) -> Optional[dict]:
    for sess in state.get("sessions", []):
        if not _session_is_active(sess):
            continue
        if str(sess.get("account_name", "")).strip().lower() != account_name.strip().lower():
            continue
        if str(sess.get("device_id", "")).strip() != device_id.strip():
            continue
        return sess
    return None


def _is_session_token_valid(token: str) -> bool:
    if not token:
        return False
    with ACCESS_LOCK:
        state = _load_access_state()
        ok = False
        for sess in state.get("sessions", []):
            if str(sess.get("token", "")).strip() == token and _session_is_active(sess):
                ok = True
                break
        _save_access_state(state)
        return ok


def _require_token(token: Optional[str], x_agent_token: Optional[str]) -> None:
    configured = _configured_api_token()
    provided = (token or x_agent_token or _extract_header_token() or "").strip()

    if not configured:
        return

    if not provided:
        raise HTTPException(status_code=401, detail="Autorisation requise: token maitre ou session validee")

    if provided == configured:
        return

    if _is_session_token_valid(provided):
        return

    raise HTTPException(status_code=403, detail="Token invalide ou session non validee")


def _require_admin_token(admin_token: Optional[str], x_admin_token: Optional[str]) -> str:
    configured = _configured_admin_token()
    provided = (admin_token or x_admin_token or _extract_header_token() or "").strip()

    if not configured:
        return ""

    if not provided:
        raise HTTPException(status_code=401, detail="Token admin requis")

    if provided != configured:
        raise HTTPException(status_code=403, detail="Token admin invalide")

    return provided


@app.get("/version")
def version() -> dict:
    return {"version": "1.0.0"}


@app.on_event("startup")
def _startup_checks() -> None:
    if not _configured_api_token():
        raise RuntimeError("API_TOKEN manquant. Le serveur refuse de demarrer sans token.")
    init_audit_schema()


@app.middleware("http")
async def _security_middleware(request, call_next):
    token = REQUEST_AUTHORIZATION.set(request.headers.get("Authorization", ""))
    try:
        path = request.url.path
        if path not in PUBLIC_PATHS and not path.startswith("/static/") and not path.startswith("/assets/"):
            provided = (request.headers.get("X-Agent-Token") or request.query_params.get("token") or request.headers.get("Authorization") or "").strip()
            if not _configured_api_token():
                raise HTTPException(status_code=503, detail="API_TOKEN manquant")
            if not provided:
                raise HTTPException(status_code=401, detail="Token requis")
            token_value = provided.split(" ", 1)[1].strip() if provided.lower().startswith("bearer ") else provided
            if token_value != _configured_api_token() and not _is_session_token_valid(token_value):
                raise HTTPException(status_code=403, detail="Token invalide")
        response = await call_next(request)
        if path not in {"/health", "/version"}:
            actor = (request.headers.get("X-Agent-Token") or request.query_params.get("token") or "anonymous")[:16]
            write_audit(actor, f"{request.method} {path} {response.status_code}", request.client.host if request.client else "127.0.0.1")
        return response
    finally:
        REQUEST_AUTHORIZATION.reset(token)


def _journal_summary() -> dict:
    if not JOURNAL_FILE.exists():
        return {"total": 0, "pending": 0, "win": 0, "loss": 0, "expired": 0, "error": 0}

    total = pending = win = loss = expired = err = 0
    by_symbol = {}

    for line in JOURNAL_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue

        total += 1
        status = str(row.get("status", "")).upper()
        symbol = row.get("symbol", "N/A")
        by_symbol.setdefault(symbol, {"total": 0, "win": 0, "loss": 0})
        by_symbol[symbol]["total"] += 1

        if status == "PENDING":
            pending += 1
        elif status == "WIN":
            win += 1
            by_symbol[symbol]["win"] += 1
        elif status == "LOSS":
            loss += 1
            by_symbol[symbol]["loss"] += 1
        elif status == "EXPIRED":
            expired += 1
        elif status in {"ERROR", "NO_DATA"}:
            err += 1

    hit_rate = (win / (win + loss) * 100.0) if (win + loss) else 0.0
    return {
        "total": total,
        "pending": pending,
        "win": win,
        "loss": loss,
        "expired": expired,
        "error": err,
        "hit_rate_pct": round(hit_rate, 2),
        "by_symbol": by_symbol,
    }



def _access_summary() -> dict:
    with ACCESS_LOCK:
        state = _load_access_state()
        pending = sum(1 for r in state.get("requests", []) if str(r.get("status", "")).upper() == "PENDING")
        active = sum(1 for s in state.get("sessions", []) if _session_is_active(s))
        _save_access_state(state)
    return {"pending_requests": pending, "active_sessions": active}
@app.get("/health")
def health() -> dict:
    configured = bool(_configured_api_token())
    llm = load_llm_settings()
    mt5_env = {
        "path": bool((os.getenv("MT5_PATH") or "").strip()),
        "login": bool((os.getenv("MT5_LOGIN") or "").strip()),
        "password": bool((os.getenv("MT5_PASSWORD") or "").strip()),
        "server": bool((os.getenv("MT5_SERVER") or "").strip()),
    }
    return {
        "status": "ok",
        "authorization_required": configured,
        "token_configured": configured,
        "approval_flow_enabled": configured,
        "access": _access_summary(),
        "llm": {
            "provider": llm.provider,
            "base_url": llm.base_url,
            "text_model": llm.text_model,
            "vision_model": llm.vision_model,
            "api_key_configured": bool(llm.api_key),
        },
        "mt5_env": mt5_env,
    }



@app.post("/access/request")
def access_request(payload: dict) -> dict:
    account_name = str(payload.get("account_name") or payload.get("name") or "").strip()
    device_name = str(payload.get("device_name") or "Telephone").strip()
    device_id = str(payload.get("device_id") or "").strip()

    if not account_name:
        raise HTTPException(status_code=400, detail="account_name requis")

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id requis")

    if len(account_name) > 80:
        raise HTTPException(status_code=400, detail="account_name trop long")

    with ACCESS_LOCK:
        state = _load_access_state()

        existing = _find_active_session_for_device(state, account_name=account_name, device_id=device_id)
        if existing:
            _save_access_state(state)
            return {
                "ok": True,
                "request_id": existing.get("request_id"),
                "status": "APPROVED",
                "token": existing.get("token"),
                "expires_at": existing.get("expires_at"),
                "message": "Session deja validee pour cet appareil",
            }

        for req in state.get("requests", []):
            if str(req.get("status", "")).upper() != "PENDING":
                continue
            if str(req.get("device_id", "")).strip() != device_id:
                continue
            req["account_name"] = account_name
            req["device_name"] = device_name
            req["updated_at"] = _utc_now_iso()
            request_id = str(req.get("id"))
            _save_access_state(state)
            return {
                "ok": True,
                "request_id": request_id,
                "status": "PENDING",
                "message": "Demande deja en attente",
                "poll_after_sec": 5,
            }

        request_id = uuid.uuid4().hex
        now = _utc_now_iso()
        state["requests"].append(
            {
                "id": request_id,
                "account_name": account_name,
                "device_name": device_name,
                "device_id": device_id,
                "status": "PENDING",
                "created_at": now,
                "updated_at": now,
                "approved_by": "",
                "note": "",
            }
        )
        _save_access_state(state)

    return {
        "ok": True,
        "request_id": request_id,
        "status": "PENDING",
        "message": "Demande envoyee. Validation requise sur dashboard desktop.",
        "poll_after_sec": 5,
    }


@app.get("/access/request/status")
def access_request_status(request_id: str = Query(...)) -> dict:
    with ACCESS_LOCK:
        state = _load_access_state()
        req = _find_request(state, request_id)
        if not req:
            _save_access_state(state)
            raise HTTPException(status_code=404, detail="Demande introuvable")

        status = str(req.get("status", "PENDING")).upper()
        out = {
            "ok": True,
            "request_id": request_id,
            "status": status,
            "account_name": req.get("account_name"),
            "device_name": req.get("device_name"),
            "updated_at": req.get("updated_at"),
            "note": req.get("note", ""),
        }

        if status == "APPROVED":
            sess = _find_session_by_request(state, request_id)
            if sess:
                out["token"] = sess.get("token")
                out["expires_at"] = sess.get("expires_at")

        _save_access_state(state)
        return out


@app.get("/admin/access/requests")
def admin_access_requests(
    admin_token: Optional[str] = Query(default=None),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_token(admin_token, x_admin_token)

    with ACCESS_LOCK:
        state = _load_access_state()
        requests = sorted(
            state.get("requests", []),
            key=lambda x: str(x.get("updated_at", "")),
            reverse=True,
        )
        sessions = sorted(
            state.get("sessions", []),
            key=lambda x: str(x.get("approved_at", "")),
            reverse=True,
        )

        rows = []
        for req in requests:
            req_id = str(req.get("id"))
            sess = _find_session_by_request(state, req_id)
            rows.append(
                {
                    **req,
                    "token_preview": _mask_token(sess.get("token", "")) if sess else "",
                    "session_active": bool(sess),
                    "session_expires_at": sess.get("expires_at") if sess else None,
                }
            )

        ses_rows = []
        for sess in sessions:
            ses_rows.append(
                {
                    **sess,
                    "token_preview": _mask_token(str(sess.get("token", ""))),
                    "active": _session_is_active(sess),
                    "token": None,
                }
            )

        pending = sum(1 for r in requests if str(r.get("status", "")).upper() == "PENDING")
        active = sum(1 for s in sessions if _session_is_active(s))
        _save_access_state(state)

    return {
        "ok": True,
        "summary": {"pending_requests": pending, "active_sessions": active, "total_requests": len(requests)},
        "requests": rows,
        "sessions": ses_rows,
    }


@app.post("/admin/access/requests/{request_id}/approve")
def admin_access_approve(
    request_id: str,
    payload: dict,
    admin_token: Optional[str] = Query(default=None),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_token(admin_token, x_admin_token)

    duration_hours = payload.get("duration_hours", 24)
    note = str(payload.get("note") or "").strip()
    approved_by = str(payload.get("approved_by") or "DESKTOP_ADMIN").strip() or "DESKTOP_ADMIN"

    try:
        duration_hours = int(duration_hours)
    except Exception:
        duration_hours = 24
    duration_hours = max(1, min(720, duration_hours))

    with ACCESS_LOCK:
        state = _load_access_state()
        req = _find_request(state, request_id)
        if not req:
            _save_access_state(state)
            raise HTTPException(status_code=404, detail="Demande introuvable")

        status = str(req.get("status", "PENDING")).upper()
        if status == "APPROVED":
            sess = _find_session_by_request(state, request_id)
            if sess:
                _save_access_state(state)
                return {
                    "ok": True,
                    "status": "APPROVED",
                    "request_id": request_id,
                    "token": sess.get("token"),
                    "expires_at": sess.get("expires_at"),
                    "message": "Demande deja approuvee",
                }

        if status not in {"PENDING", "APPROVED"}:
            _save_access_state(state)
            raise HTTPException(status_code=409, detail=f"Demande deja traitee ({status})")

        now = _utc_now()
        expires_at = (now + timedelta(hours=duration_hours)).isoformat()
        token = "USR-" + secrets.token_urlsafe(24)

        session_row = {
            "request_id": request_id,
            "token": token,
            "account_name": req.get("account_name", ""),
            "device_name": req.get("device_name", ""),
            "device_id": req.get("device_id", ""),
            "approved_by": approved_by,
            "approved_at": now.isoformat(),
            "expires_at": expires_at,
            "active": True,
            "revoked_at": "",
            "revoked_reason": "",
        }

        req["status"] = "APPROVED"
        req["approved_by"] = approved_by
        req["updated_at"] = now.isoformat()
        req["note"] = note
        state["sessions"].append(session_row)
        _save_access_state(state)

    return {
        "ok": True,
        "status": "APPROVED",
        "request_id": request_id,
        "token": token,
        "expires_at": expires_at,
        "account_name": req.get("account_name", ""),
        "device_name": req.get("device_name", ""),
    }


@app.post("/admin/access/requests/{request_id}/reject")
def admin_access_reject(
    request_id: str,
    payload: dict,
    admin_token: Optional[str] = Query(default=None),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_token(admin_token, x_admin_token)

    note = str(payload.get("note") or "Refuse par admin").strip()
    with ACCESS_LOCK:
        state = _load_access_state()
        req = _find_request(state, request_id)
        if not req:
            _save_access_state(state)
            raise HTTPException(status_code=404, detail="Demande introuvable")

        status = str(req.get("status", "PENDING")).upper()
        if status != "PENDING":
            _save_access_state(state)
            raise HTTPException(status_code=409, detail=f"Demande deja traitee ({status})")

        req["status"] = "REJECTED"
        req["updated_at"] = _utc_now_iso()
        req["note"] = note
        _save_access_state(state)

    return {"ok": True, "status": "REJECTED", "request_id": request_id, "note": note}


@app.post("/admin/access/sessions/revoke")
def admin_access_revoke_session(
    payload: dict,
    admin_token: Optional[str] = Query(default=None),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _require_admin_token(admin_token, x_admin_token)

    request_id = str(payload.get("request_id") or "").strip()
    token_preview = str(payload.get("token_preview") or "").strip()
    if not request_id and not token_preview:
        raise HTTPException(status_code=400, detail="request_id ou token_preview requis")

    revoked = False
    with ACCESS_LOCK:
        state = _load_access_state()
        for sess in state.get("sessions", []):
            if not bool(sess.get("active", False)):
                continue

            if request_id and str(sess.get("request_id", "")).strip() == request_id:
                sess["active"] = False
                sess["revoked_at"] = _utc_now_iso()
                sess["revoked_reason"] = "manual"
                revoked = True

            if token_preview and _mask_token(str(sess.get("token", ""))) == token_preview:
                sess["active"] = False
                sess["revoked_at"] = _utc_now_iso()
                sess["revoked_reason"] = "manual"
                revoked = True

        _save_access_state(state)

    if not revoked:
        raise HTTPException(status_code=404, detail="Session active introuvable")

    return {"ok": True, "revoked": True}
@app.post("/bridge/market-data")
async def bridge_market_data(
    payload: dict,
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    p = save_bridge_market_data(payload)
    return {"ok": True, "saved": str(p)}


@app.get("/manager/analyze")
def manager_analyze(
    symbol: str = Query(...),
    risk_pct: float = Query(1.0, gt=0),
    mode: str = Query("manual"),
    rr_min: float = Query(2.5, ge=1.0),
    auto_enabled: bool = Query(False),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    allow_auto = auto_enabled and os.getenv("AFR_AUTO_ENABLED", "0").strip() == "1"
    return analyze_symbol_manager(symbol=symbol, risk_pct=risk_pct, rr_min=rr_min, mode=mode, auto_enabled=allow_auto)


@app.post("/manager/screenshot")
async def manager_screenshot(
    file: UploadFile = File(...),
    context: str = Form(default=""),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    out = SCREEN_DIR / file.filename
    try:
        out.write_bytes(await file.read())
        analysis = analyze_chart_screenshot(str(out), context=context)
        return {"ok": True, "file": str(out), "analysis": analysis}
    except Exception as exc:
        return {
            **_degraded_mt5_response("manager_screenshot", exc),
            "file": str(out),
            "analysis": "Analyse screenshot indisponible pour le moment.",
        }


@app.post("/manager/journal/add")
def manager_journal_add(
    payload: dict,
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    saved = add_trade_review(payload)
    return {"ok": True, "saved": saved}


@app.get("/manager/journal/summary")
def manager_journal_summary(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return manager_summary()


@app.get("/live/brief")
def live_brief(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {"content": _read_text(LIVE_DIR / "realtime_brief.txt")}


@app.get("/live/signals")
def live_signals(
    symbols: str = Query("EURUSDm,XAUUSDm,BTCUSDm"),
    timeframes: str = Query("M5,M15"),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in timeframes.split(",") if t.strip()]
    try:
        payload = build_live_signal_pack(symbols=syms, timeframes=tfs)
        payload.setdefault("ok", True)
        payload.setdefault("status", "ok")
        return payload
    except Exception as exc:
        cached = _read_json(SIGNALS_FILE)
        if isinstance(cached, dict):
            cached.setdefault("signals", [])
            cached.setdefault("errors", [])
            cached.update(_degraded_mt5_response("live_signals", exc))
            cached["from_cache"] = bool(cached.get("signals"))
            return cached
        return {
            **_degraded_mt5_response("live_signals", exc),
            "signals": [],
            "errors": [],
            "from_cache": False,
        }


@app.post("/live/learning/evaluate")
def learning_evaluate(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    try:
        data = evaluate_pending_signals()
        data.setdefault("ok", True)
        data.setdefault("status", "ok")
        return data
    except Exception as exc:
        return {
            **_degraded_mt5_response("learning_evaluate", exc),
            "updated": 0,
            "journal_count": 0,
        }


@app.get("/live/state")
def live_state(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {
        "brief": _read_text(LIVE_DIR / "realtime_brief.txt"),
        "signals": _read_json(LIVE_DIR / "mt5_live_signals.json"),
        "learning": _read_json(LIVE_DIR / "learning_state.json"),
        "training_metrics": _read_json(METRICS_FILE),
        "journal_summary": _journal_summary(),
        "manager_journal": manager_summary(),
        "agent_intel": _read_json(AGENT_INTEL_FILE),
        "profit_mode": _read_json(PROFIT_MODE_STATE_FILE),
    }



@app.get("/live/agent-intel")
def live_agent_intel(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return _read_json(AGENT_INTEL_FILE)


@app.get("/live/profit-mode/state")
def live_profit_mode_state(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return _read_json(PROFIT_MODE_STATE_FILE)

@app.get("/live/diagnostics")
def live_diagnostics(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)

    metrics = _read_json(METRICS_FILE)
    signals = _read_json(SIGNALS_FILE)
    last_log_lines = _read_text(LOG_FILE).splitlines()[-20:]
    last_error = ""
    for line in reversed(last_log_lines):
        if "ERROR" in line.upper():
            last_error = line
            break

    return {
        "status": "ok",
        "files": {
            "metrics_exists": METRICS_FILE.exists(),
            "signals_exists": SIGNALS_FILE.exists(),
            "log_exists": LOG_FILE.exists(),
        },
        "runtime": {
            "last_error": last_error,
            "signal_count": len(signals.get("signals", [])) if isinstance(signals, dict) else 0,
            "signal_status": (signals.get("status") if isinstance(signals, dict) else None),
            "signal_from_cache": (signals.get("from_cache") if isinstance(signals, dict) else None),
            "metrics": metrics,
            "log_tail": last_log_lines,
        },
    }
@app.get("/live/training/metrics")
def training_metrics(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return _read_json(METRICS_FILE)


@app.get("/live/training/log")
def training_log(
    lines: int = Query(80, ge=10, le=500),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    content = _read_text(LOG_FILE)
    arr = content.splitlines()
    return {"lines": arr[-lines:]}


@app.get("/live/execution/candidates")
def execution_candidates(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {"candidates": list_candidates()}


@app.post("/live/execution/preview")
def execution_preview(
    signal_id: int = Query(..., ge=1),
    risk_pct: float = Query(1.0, gt=0),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    r = execute_signal(signal_id=signal_id, risk_pct=risk_pct, live=False)
    return {"ok": r.ok, "mode": r.mode, "message": r.message, "payload": r.payload}


@app.post("/live/execution/place")
def execution_place(
    signal_id: int = Query(..., ge=1),
    risk_pct: float = Query(1.0, gt=0),
    confirm: str = Query(""),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    r = execute_signal(signal_id=signal_id, risk_pct=risk_pct, live=True, confirm=confirm)
    return {"ok": r.ok, "mode": r.mode, "message": r.message, "payload": r.payload}



@app.get("/desktop", response_class=HTMLResponse)
def desktop_simple() -> str:
    html = _read_text(DESKTOP_SIMPLE_FILE)
    if not html:
        return "<h1>Interface desktop introuvable</h1>"
    return html



@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard() -> str:
    html = _read_text(ADMIN_DASHBOARD_FILE)
    if not html:
        return "<h1>Dashboard admin introuvable</h1>"
    return html

@app.get("/changelog", response_class=HTMLResponse)
def changelog() -> str:
    html = _read_text(ROOT / "web" / "changelog.html")
    if not html:
        return "<h1>Changelog introuvable</h1>"
    return html
@app.get("/simple/status")
def simple_status(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1h"),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {"ok": True, "status": simple_strategy_status(symbol=symbol, interval=interval)}


@app.post("/simple/strategy/run")
def simple_strategy_run(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1h"),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {"ok": True, "result": simple_run_strategy_cycle(symbol=symbol, interval=interval)}


@app.get("/simple/trades")
def simple_trades(
    status: str = Query("ALL"),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return {"ok": True, "trades": simple_list_trades(status=status)}


@app.post("/simple/trades/open")
def simple_trades_open(
    symbol: str = Query(...),
    side: str = Query(...),
    mt5_symbol: str = Query(""),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    try:
        trade = simple_open_trade(symbol=symbol, side=side, source="manual", mt5_symbol=mt5_symbol or None)
        return {"ok": True, "trade": trade}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@app.post("/simple/trades/close")
def simple_trades_close(
    trade_id: str = Query(...),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    try:
        trade = simple_close_trade(trade_id=trade_id, reason="manual_close")
        return {"ok": True, "trade": trade}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@app.post("/simple/trades/sync")
def simple_trades_sync(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    try:
        return {"ok": True, "result": simple_sync_trades()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@app.post("/simple/mt5/execute")
def simple_mt5_execute(
    trade_id: str = Query(...),
    risk_pct: float = Query(1.0, gt=0),
    confirm: str = Query(""),
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> dict:
    _require_token(token, x_agent_token)
    return simple_execute_trade_on_mt5(trade_id=trade_id, risk_pct=risk_pct, confirm=confirm)
@app.get("/manifest.webmanifest")
def manifest() -> Response:
    p = ROOT / "web" / "manifest.webmanifest"
    return Response(content=_read_text(p), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> Response:
    p = ROOT / "web" / "sw.js"
    return Response(content=_read_text(p), media_type="application/javascript")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    html = _read_text(DASHBOARD_FILE)
    if not html:
        return "<h1>Dashboard introuvable</h1>"
    return html


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return dashboard_page()


@app.get("/raw/signals")
def raw_signals(
    token: Optional[str] = Query(default=None),
    x_agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
) -> JSONResponse:
    _require_token(token, x_agent_token)
    return JSONResponse(content=_read_json(LIVE_DIR / "mt5_live_signals.json"))













