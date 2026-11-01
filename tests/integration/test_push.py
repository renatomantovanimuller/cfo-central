"""Web Push: chaves do servidor, inscrição de aparelhos e envio pelo resumo diário sem e-mail configurado."""


def _sub(n=1):
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/abc{n}",
            "keys": {"p256dh": "BOrrfpxGm4Zz2iVVo7aQkF0qBcf2s0yQzG6hR7Xq3t2b9ZcLwq3vJ8sT0bUf7Yd1nKp0mW4xA5eR6tY7uI8oP9Q", "auth": "aaaaaaaaaaaaaaaaaaaaaa"}}


def test_chaves_estaveis_e_inscricao(db_reset):
    from app.alerts import push
    with db_reset() as s:
        k1 = push.vapid(s)["public_key"]
        assert push.vapid(s)["public_key"] == k1 and len(k1) > 80
        out = push.subscribe(s, _sub(), "Celular")
        push.subscribe(s, _sub(), "Celular de novo")  # mesmo endpoint: não duplica
        assert len(push.subscriptions(s)) == 1 and out["aparelhos"][0]["origem"] == "Android / Chrome"
        try:
            push.subscribe(s, {"endpoint": "http://x"}, None)
            raise AssertionError("aceitou inscrição inválida")
        except ValueError:
            pass
        push.unsubscribe(s, out["aparelhos"][0]["id"])
        assert push.subscriptions(s) == []


def test_resumo_vai_pelo_push_e_nao_repete(db_reset, monkeypatch):
    import pywebpush
    from app.alerts import notify, push
    from app.models import ReviewItem
    sent = []

    def fake(sub, data, **kw):
        sent.append((sub["endpoint"], data))
    monkeypatch.setattr(pywebpush, "webpush", fake)
    monkeypatch.setattr("app.analytics.plano.safe_to_spend", lambda s: {"disponivel": 100.0, "por_dia": 10.0,
                                                                     "dias_restantes": 10, "gasto_ate_hoje": 50.0})
    with db_reset() as s:
        push.subscribe(s, _sub(), None)
        s.add(ReviewItem(fingerprint="x1", kind="anomaly", severity="high", entity_type="transaction", entity_id="t1",
                         title="Gasto fora do padrão", detail="R$ 900", status="open"))
        s.flush()
        r = notify.daily_digest(s)
        assert r["sent"] and r.get("push") and not r.get("email")
        assert len(sent) == 1 and "Gasto fora do padrão" in sent[0][1]
        assert notify.daily_digest(s)["sent"] is False  # já avisado
        assert notify.notify_once(s, "teste:1", "Título", "Corpo")["sent"]
        assert notify.notify_once(s, "teste:1", "Título", "Corpo")["sent"] is False


def test_inscricao_expirada_sai(db_reset, monkeypatch):
    import pywebpush
    from app.alerts import push

    class R:
        status_code = 410
        text = "gone"

    def gone(sub, data, **kw):
        raise pywebpush.WebPushException("gone", response=R())
    monkeypatch.setattr(pywebpush, "webpush", gone)
    with db_reset() as s:
        push.subscribe(s, _sub(), None)
        assert push.send(s, "t", "b")["sent"] == 0
        assert push.subscriptions(s) == []
