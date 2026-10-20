from __future__ import annotations

from app.accounting.statements import dre, month_list
from app.analytics.overview import kpis_from_dre
from app.alerts.reviews import fmt_brl
from app.accounting.balance import current_position
from app.database.session import session_scope


def print_summary() -> None:
    with session_scope() as s:
        months = month_list(n=6)
        k = kpis_from_dre(dre(s, months, with_valuation=False))
        t = current_position(s)["totals"]
    print(f"Patrimônio líquido: {fmt_brl(t['net_worth'])}  (caixa {fmt_brl(t['cash'])}, "
          f"investimentos {fmt_brl(t['investments'])}, cartões −{fmt_brl(t['card_current'] + t['card_future'])})")
    print(f"{'mês':8} {'receita líq.':>14} {'despesas':>14} {'resultado':>14} {'poupança':>9}")
    for m in months:
        x = k[m]
        sr = f"{x['taxa_poupanca']:.0%}" if x["taxa_poupanca"] is not None else "—"
        print(f"{m:8} {fmt_brl(x['receita_liquida']):>14} {fmt_brl(x['despesas']):>14} {fmt_brl(x['resultado']):>14} {sr:>9}")
