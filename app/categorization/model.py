"""Classificador treinado nas suas decisões.

Aprende com o que já está decidido com segurança — seus ajustes manuais, suas regras e comerciantes (peso 3),
palavras-chave/MCC de alta confiança (peso 1) — e só atua onde a classificação atual é fraca (categoria genérica
da Pluggy ou nenhuma regra). Texto da descrição, comerciante e contraparte + MCC, sentido, tipo de conta,
categoria da Pluggy e faixa de valor → TF-IDF (palavras e pares) → regressão logística.

Salvaguardas:
- validação cruzada a cada mudança no conjunto de treino; o modelo só é usado se, nos lançamentos que ele não viu,
  acertar ≥ 90 % das vezes em que estiver acima do limiar de confiança;
- nunca mexe em ajuste manual, regra, conciliação estrutural (fatura, transferência, aporte) nem em Pix para
  pessoa física sem comerciante (isso é decisão sua);
- saída respeita o sentido: entrada só vira receita; saída só vira despesa;
- cada troca fica explicada em rule_id (probabilidade + termos que mais pesaram) e na auditoria do razão.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.categorization.engine import Decision, TxView
from app.categorization.text import norm

log = logging.getLogger(__name__)

THRESHOLD = 0.80
MIN_PRECISION = 0.90
MIN_SAMPLES = 60
NOT_TARGETS = {"nc", "rec.pix_terceiros"}
WEAK_SOURCES = {"pluggy_map", "default"}
_WORD = re.compile(r"[a-z]{2,}")


def features(tx: TxView) -> str:
    text = norm(" ".join(x for x in (tx.description, tx.merchant_name, tx.counterparty_name) if x))
    words = _WORD.findall(text)
    extra = [f"_dir_{'in' if tx.flow > 0 else 'out'}", f"_conta_{(tx.account_type or '').lower()}",
             f"_valor_{int(math.log2(abs(tx.flow) + 1))}"]
    if tx.mcc:
        extra.append(f"_mcc_{tx.mcc}")
    if tx.pluggy_cat:
        extra += [f"_pcat_{tx.pluggy_cat}", f"_pgrp_{tx.pluggy_cat[:4]}"]
    if tx.payment_method:
        extra.append(f"_meio_{tx.payment_method.lower()}")
    return " ".join(words + extra)


def _label(tx: TxView, d: Decision, cats: dict) -> tuple[str, float] | None:
    """(categoria, peso) quando a decisão atual é confiável para treinar."""
    if tx.removed or d.category_id in NOT_TARGETS or d.category_id not in cats:
        return None
    if d.event_type not in (None, "EXPENSE", "INCOME"):
        return None
    cat = cats[d.category_id]
    if cat.nature not in ("despesa", "receita", "financeiro", "imposto"):
        return None
    if d.rule_source in ("manual", "rule"):
        return d.category_id, 3.0
    if d.rule_source == "merchant":
        return d.category_id, 3.0 if d.confidence >= 0.85 else 1.0
    if d.rule_source == "heuristic" and (d.rule_id or "").startswith(("keyword:", "mcc:")) and d.confidence >= 0.8:
        return d.category_id, 1.0
    return None


def _candidate(tx: TxView, d: Decision) -> bool:
    if tx.removed or d.event_type is not None or abs(tx.flow) < 0.01:
        return False
    if not (d.rule_source in WEAK_SOURCES or (d.rule_source == "heuristic" and d.confidence < 0.7)):
        return False
    doc = tx.counterparty_doc or ""
    if len(doc) == 11 and not tx.merchant_name:  # Pix/TED para pessoa: decisão do usuário, não do modelo
        return False
    return True


def _allowed(cat, flow: float) -> bool:
    if cat is None:
        return False
    if flow > 0:
        return cat.nature == "receita" or (cat.id or "").startswith("finrec")
    return cat.nature in ("despesa", "imposto") or (cat.nature == "financeiro" and not (cat.id or "").startswith("finrec"))


def _fit(X_text, y, w):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    vec = TfidfVectorizer(token_pattern=r"[^ ]+", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    X = vec.fit_transform(X_text)
    clf = LogisticRegression(C=8.0, max_iter=4000)
    clf.fit(X, y, sample_weight=w)
    return vec, clf


def _cross_validate(X_text, y, w, k: int = 5) -> dict:
    """Probabilidade fora da amostra para cada exemplo → acurácia e precisão acima do limiar."""
    import numpy as np
    n = len(y)
    order = np.random.RandomState(7).permutation(n)
    folds = [order[i::k] for i in range(k)]
    hits = conf_hits = conf_n = 0
    for f in folds:
        test = set(f.tolist())
        tr = [i for i in range(n) if i not in test]
        if len(set(y[i] for i in tr)) < 2:
            continue
        vec, clf = _fit([X_text[i] for i in tr], [y[i] for i in tr], [w[i] for i in tr])
        P = clf.predict_proba(vec.transform([X_text[i] for i in f]))
        for row, i in zip(P, f):
            j = int(row.argmax())
            ok = clf.classes_[j] == y[i]
            hits += ok
            if row[j] >= THRESHOLD:
                conf_n += 1
                conf_hits += ok
    return {"acuracia": round(hits / n, 4) if n else None,
            "precisao_no_limiar": round(conf_hits / conf_n, 4) if conf_n else None,
            "cobertura_no_limiar": round(conf_n / n, 4) if n else None}


def _explain(vec, clf, x_row, cls_idx: int, top: int = 3) -> list[str]:
    names = vec.get_feature_names_out()
    coef = clf.coef_[cls_idx] if clf.coef_.shape[0] > 1 else clf.coef_[0]
    contrib = x_row.multiply(coef).tocsr()
    pairs = sorted(zip(contrib.indices, contrib.data), key=lambda p: -p[1])
    out = []
    for idx, val in pairs:
        if val <= 0:
            break
        out.append(names[idx].replace("_pcat_", "pluggy:").replace("_mcc_", "mcc:").replace("_", ""))
        if len(out) >= top:
            break
    return out


def _save(s: Session, info: dict) -> None:
    from app.models import AppSetting
    from app.utils.time import utcnow
    row = s.get(AppSetting, "classificador") or AppSetting(key="classificador")
    row.value = {**info, "treinado_em": utcnow().isoformat()}
    s.add(row)
    s.flush()


def apply_model(s: Session, decided: dict, cats: dict) -> dict:
    """Treina, valida e aplica. Altera `decided` no lugar. Devolve o resumo (também salvo em app_settings)."""
    from app.analytics.plano import get_setting
    try:
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError:
        return {"habilitado": False, "motivo": "scikit-learn não instalado"}

    samples = []
    for tx, d, _, _ in decided.values():
        lab = _label(tx, d, cats)
        if lab:
            samples.append((tx, lab[0], lab[1]))
    counts = Counter(c for _, c, _ in samples)
    samples = [x for x in samples if counts[x[1]] >= 3]
    info: dict = {"amostras": len(samples), "classes": len({c for _, c, _ in samples}),
                  "decisoes_suas": sum(1 for _, _, w in samples if w >= 3), "limiar": THRESHOLD}
    if len(samples) < MIN_SAMPLES or info["classes"] < 3:
        info.update(habilitado=False, motivo=f"poucos exemplos confiáveis ({len(samples)})")
        _save(s, info)
        return info

    X_text = [features(tx) for tx, _, _ in samples]
    y = [c for _, c, _ in samples]
    w = [wt for _, _, wt in samples]
    h = hashlib.sha1("|".join(f"{tx.id}:{c}:{wt}" for tx, c, wt in sorted(samples, key=lambda x: x[0].id))
                     .encode()).hexdigest()[:16]
    prev = get_setting(s, "classificador")
    if prev.get("hash") == h and prev.get("validacao"):
        cv = prev["validacao"]
    else:
        cv = _cross_validate(X_text, y, w)
    info.update(hash=h, validacao=cv)
    usable = (cv.get("precisao_no_limiar") or 0) >= MIN_PRECISION
    info["habilitado"] = usable
    if not usable:
        info["motivo"] = (f"precisão na validação {cv.get('precisao_no_limiar') or 0:.0%} < {MIN_PRECISION:.0%}: "
                          "modelo não aplicado")
        _save(s, info)
        return info

    vec, clf = _fit(X_text, y, w)
    classes = list(clf.classes_)
    cand = [(tid, tx, d) for tid, (tx, d, _, _) in decided.items() if _candidate(tx, d)]
    changed, confirmed, examples = 0, 0, []
    if cand:
        Xc = vec.transform([features(tx) for _, tx, _ in cand])
        P = clf.predict_proba(Xc)
        for row_i, ((tid, tx, d), row) in enumerate(zip(cand, P)):
            ranked = sorted(range(len(classes)), key=lambda j: -row[j])
            j = next((j for j in ranked if _allowed(cats.get(classes[j]), tx.flow)), None)
            if j is None:
                continue
            p = float(row[j])
            if p < THRESHOLD:  # mesmo limiar medido na validação cruzada
                continue
            target = classes[j]
            why = _explain(vec, clf, Xc[row_i], j)
            tag = f"modelo:{p:.2f}:{','.join(why)}"[:80]
            cur_tx, cur_d, m, o = decided[tid]
            if target == d.category_id:
                confirmed += 1
                decided[tid] = (cur_tx, Decision(d.category_id, d.event_type, d.rule_source,
                                                 f"{d.rule_id or ''}+modelo:{p:.2f}"[:80], max(d.confidence, min(p, 0.9)),
                                                 list(d.review), d.transfer_id, d.merchant_id), m, o)
                continue
            changed += 1
            decided[tid] = (cur_tx, Decision(target, None, "modelo", tag, round(min(p, 0.9), 3), list(d.review),
                                             d.transfer_id, d.merchant_id), m, o)
            if len(examples) < 40:
                examples.append({"tx_id": tid, "data": tx.date.isoformat(), "descricao": tx.description,
                                 "valor": round(tx.flow, 2), "de": d.category_id, "para": target,
                                 "probabilidade": round(p, 3), "termos": why})
    info.update(candidatos=len(cand), reclassificados=changed, confirmados=confirmed, exemplos=examples)
    _save(s, info)
    return info

