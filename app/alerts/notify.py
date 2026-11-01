"""Alertas por e-mail e no celular (Web Push): resumo diário de itens novos da revisão (graves/atenção) e fechamento
do mês. Sem nenhum canal configurado, nada é enviado e o motivo aparece em Configurações. Cada aviso vai uma vez só,
pelo canal que estiver ligado (os dois, se ambos estiverem)."""
from __future__ import annotations

import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import push
from app.alerts.reviews import fmt_brl
from app.config.settings import get_settings
from app.models import NotificationLog, ReviewItem
from app.utils.time import month_add, month_key, today_brt, utcnow

SEV_LABEL = {"high": "Grave", "warn": "Atenção"}


def _send(subject: str, body_html: str) -> None:
    st = get_settings()
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, st.smtp_user, st.alert_email_to or st.smtp_user
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP(st.smtp_host, st.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(st.smtp_user, st.smtp_password)
        smtp.send_message(msg)


def _log(s: Session, fingerprint: str, subject: str, status: str = "sent", error: str | None = None) -> None:
    s.add(NotificationLog(channel="email", fingerprint=fingerprint, subject=subject[:300], status=status, error=error))


def _page(title: str, sections: list[tuple[str, str]]) -> str:
    body = "".join(f"<h3 style='margin:18px 0 6px;font:600 15px system-ui'>{html.escape(h)}</h3>{c}" for h, c in sections)
    return (f"<div style='font:14px/1.5 system-ui;color:#14231f;max-width:640px'>"
            f"<h2 style='font:700 18px system-ui;color:#0f5c4a'>{html.escape(title)}</h2>{body}"
            f"<p style='color:#6b7a75;font-size:12px;margin-top:20px'>CFO Central · http://127.0.0.1:8060</p></div>")


def send_test(s: Session) -> dict:
    st = get_settings()
    if not st.email_enabled:
        return {"ok": False, "erro": "e-mail não configurado (informe em Configurações)"}
    try:
        _send("CFO Central: teste de alerta", _page("Teste de alerta", [("Tudo certo", "<p>Os alertas por e-mail estão funcionando.</p>")]))
        _log(s, f"test:{utcnow().isoformat()}", "teste")
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e)[:300]}


def daily_digest(s: Session) -> dict:
    """Itens novos de severidade grave/atenção ainda não avisados + 'quanto posso gastar'."""
    st = get_settings()
    email_on, push_on = st.email_enabled, push.enabled(s)
    if not (email_on or push_on):
        return {"sent": False, "reason": "nenhum canal configurado"}
    sent = {f for (f,) in s.execute(select(NotificationLog.fingerprint).where(NotificationLog.status == "sent"))}
    items = [r for r in s.scalars(select(ReviewItem).where(ReviewItem.status == "open",
                                                             ReviewItem.severity.in_(["high", "warn"])))
             if f"review:{r.fingerprint}" not in sent]
    if not items:
        return {"sent": False, "reason": "nada novo"}
    from app.analytics.plano import safe_to_spend
    sts = safe_to_spend(s)
    rows = "".join(f"<li><b>{SEV_LABEL.get(r.severity, r.severity)}</b> · {html.escape(r.title)}"
                   f"<br><span style='color:#6b7a75'>{html.escape(r.detail or '')}</span></li>" for r in items[:25])
    subject = f"CFO Central: {len(items)} alerta(s) novo(s)"
    from app.health.checks import STATUS_LABEL, latest
    h = latest(s)
    health_html = "<p>Ainda não rodou.</p>" if not h else "<ul style='padding-left:18px'>" + "".join(
        f"<li><b>{STATUS_LABEL.get(v['status'], v['status'])}</b> · {html.escape(v['titulo'])}: {html.escape(v['resumo'])}</li>"
        for v in h["verificacoes"] if v["status"] in ("falha", "atencao")) + "</ul>"
    if h and not any(v["status"] in ("falha", "atencao") for v in h["verificacoes"]):
        health_html = f"<p>Todas as {len(h['verificacoes'])} conferências estão OK.</p>"
    page = _page(subject, [
        ("Saúde dos dados", health_html),
        ("Alertas", f"<ul style='padding-left:18px'>{rows}</ul>"),
        ("Quanto posso gastar este mês",
         f"<p>{fmt_brl(sts['disponivel'])} disponíveis ({fmt_brl(sts['por_dia'] or 0)} por dia, "
         f"{sts['dias_restantes']} dias). Gasto até hoje: {fmt_brl(sts['gasto_ate_hoje'])}.</p>"),
    ])
    out: dict = {"items": len(items)}
    if email_on:
        try:
            _send(subject, page)
            out["email"] = True
        except Exception as e:  # noqa: BLE001
            _log(s, f"digest:{utcnow().date()}", subject, "error", str(e)[:500])
            out["email"] = False
            out["reason"] = str(e)[:200]
    if push_on:
        grave = sum(r.severity == "high" for r in items)
        lines = [r.title for r in sorted(items, key=lambda r: r.severity != "high")[:3]]
        more = f" e mais {len(items) - 3}" if len(items) > 3 else ""
        body = "; ".join(lines) + more + f". Disponível no mês: {fmt_brl(sts['disponivel'])}."
        title = f"{len(items)} alerta(s) novo(s)" + (f", {grave} grave(s)" if grave else "")
        out["push"] = push.send(s, title, body, url="/revisao", tag="digest", fingerprint=f"push-digest:{utcnow().date()}")["sent"] > 0
    if out.get("email") or out.get("push"):
        channel = "email" if out.get("email") else "push"
        for r in items:
            s.add(NotificationLog(channel=channel, fingerprint=f"review:{r.fingerprint}", subject=subject[:300]))
    out["sent"] = bool(out.get("email") or out.get("push"))
    return out


def monthly_close(s: Session, month: str | None = None) -> dict:
    """Resumo do mês fechado (DRE gerencial) — no dia 1, sobre o mês anterior."""
    st = get_settings()
    month = month or month_add(month_key(today_brt()), -1)
    fp = f"close:{month}"
    if s.scalar(select(NotificationLog.id).where(NotificationLog.fingerprint == fp, NotificationLog.status == "sent")):
        return {"sent": False, "reason": "já enviado"}
    email_on, push_on = st.email_enabled, push.enabled(s)
    if not (email_on or push_on):
        return {"sent": False, "reason": "nenhum canal configurado"}
    from app.accounting.management import dre_gerencial
    g = dre_gerencial(s, month)
    top = [r for r in g["rows"] if r["level"] == 0]
    def tr(r):
        d = r["delta"]
        dtxt = "" if d is None else f" ({'+' if d >= 0 else ''}{fmt_brl(d)} vs média)"
        return f"<tr><td style='padding:2px 10px 2px 0'>{'<b>' if r['subtotal'] else ''}{html.escape(r['label'])}</td>" \
               f"<td style='text-align:right'>{fmt_brl(r['mes'])}{dtxt}</td></tr>"
    ind = g["indicadores"]
    def pct(x):
        return "—" if x is None else f"{x:.0%}"
    page = _page(f"Fechamento de {month}", [
        ("DRE gerencial", "<table style='border-collapse:collapse'>" + "".join(tr(r) for r in top) + "</table>"),
        ("Indicadores", f"<p>Poupança recorrente: {pct(ind['taxa_poupanca_mes'])} (média 6m {pct(ind['taxa_poupanca_6m'])}). "
                        f"Reserva líquida: {fmt_brl(ind['reserva_liquida'])} "
                        f"({(ind['meses_de_essenciais'] or 0):.1f} meses de custo essencial).</p>"),
    ])
    subject = f"CFO Central: fechamento de {month}"
    out: dict = {}
    if email_on:
        try:
            _send(subject, page)
            _log(s, fp, subject)
            out["email"] = True
        except Exception as e:  # noqa: BLE001
            _log(s, fp, subject, "error", str(e)[:500])
            out["email"], out["reason"] = False, str(e)[:200]
    if push_on:
        by_key = {r["key"]: r["mes"] for r in top}
        res = by_key.get("resultado_liquido")
        tot = by_key.get("resultado_total")
        body = (f"Resultado recorrente: {fmt_brl(res)}. " if res is not None else "") + \
            (f"Com eventuais: {fmt_brl(tot)}. " if tot is not None and res is not None and abs(tot - res) >= 1 else "") + \
            f"Poupança recorrente {pct(ind['taxa_poupanca_mes'])} (média 6m {pct(ind['taxa_poupanca_6m'])}). " \
            f"Reserva: {(ind['meses_de_essenciais'] or 0):.1f} meses de custo essencial."
        out["push"] = push.send(s, f"Fechamento de {month}", body, url="/dre-gerencial", tag=fp, fingerprint=fp)["sent"] > 0
    out["sent"] = bool(out.get("email") or out.get("push"))
    return out


def status(s: Session) -> dict:
    st = get_settings()
    last = s.scalars(select(NotificationLog).order_by(NotificationLog.id.desc()).limit(10)).all()
    return {"configurado": st.email_enabled, "push": push.enabled(s), "para": st.alert_email_to or st.smtp_user or None,
            "horario": st.alerts_hour,
            "ultimos": [{"em": n.sent_at, "assunto": n.subject, "status": n.status, "erro": n.error} for n in last]}


def notify_once(s: Session, fingerprint: str, title: str, body: str, url: str = "/") -> dict:
    """Aviso avulso (ex.: apareceu conector de benefício na Pluggy), pelos canais ligados, uma única vez."""
    if s.scalar(select(NotificationLog.id).where(NotificationLog.fingerprint == fingerprint, NotificationLog.status == "sent")):
        return {"sent": False, "reason": "já enviado"}
    st = get_settings()
    out: dict = {}
    if st.email_enabled:
        try:
            _send(f"CFO Central: {title}", _page(title, [("", f"<p>{html.escape(body)}</p>")]))
            _log(s, fingerprint, title)
            out["email"] = True
        except Exception as e:  # noqa: BLE001
            _log(s, fingerprint, title, "error", str(e)[:500])
    if push.enabled(s):
        out["push"] = push.send(s, title, body, url=url, tag=fingerprint, fingerprint=fingerprint)["sent"] > 0
    out["sent"] = bool(out.get("email") or out.get("push"))
    return out
