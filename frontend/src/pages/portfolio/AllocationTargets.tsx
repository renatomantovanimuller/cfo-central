import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api";
import { NumberInput } from "../../components/MoneyInput";
import { QueryState } from "../../components/QueryState";
import { Chip, Money, Panel } from "../../components/ui";
import { useApiMutation } from "../../hooks/useApiMutation";
import { formatInputNumber, parseBRL, pct, validateNumber } from "../../format";

const STATUS: Record<string, [string, "green" | "red" | "ochre" | undefined]> = {
  ok: ["na banda", "green"], abaixo: ["abaixo", "ochre"], acima: ["acima", "red"], "sem alvo": ["sem alvo", undefined],
};

/** Alocação atual × alvo por classe, em barras-alvo (banda sombreada, marca no alvo), com edição dos alvos na própria tela. */
export function AllocationTargets({ compact = false }: { compact?: boolean }) {
  const q = useQuery({ queryKey: ["plan-targets"], queryFn: () => api<any>("/api/plan/targets") });
  const [edit, setEdit] = useState<Record<string, string> | null>(null);
  const save = useApiMutation({
    mutationFn: (rows: { asset_class: string; target_pct: number }[]) => api("/api/plan/targets", { method: "PUT", body: rows }),
    successMessage: "Alocação-alvo salva", invalidate: "all", onSuccess: () => setEdit(null),
  });
  const d = q.data;
  if (!d) return <QueryState q={q} what="a alocação-alvo" layout="panel">{() => null}</QueryState>;
  const rows: any[] = d.classes;
  const scale = Math.min(1, Math.max(0.25, ...rows.map((r) => Math.max(r.atual ?? 0, r.max ?? 0, r.alvo ?? 0))) * 1.12);
  const x = (v: number | null | undefined) => `${Math.max(0, Math.min(100, ((v ?? 0) / scale) * 100))}%`;
  const startEdit = () => setEdit(Object.fromEntries(rows.map((r) => [r.classe, r.alvo !== null ? formatInputNumber(Math.round(r.alvo * 1000) / 10) : ""])));
  const sum = edit ? Object.values(edit).reduce((a, v) => a + (parseBRL(v) ?? 0), 0) : 0;
  const invalid = edit ? Object.values(edit).some((v) => validateNumber(v, { min: 0, max: 100 }).error) : false;
  const off = rows.filter((r) => r.status === "acima" || r.status === "abaixo").length;

  return (
    <Panel title="Alocação × alvo" hint={d.alvos_definidos ? (off ? `${off} ${off === 1 ? "classe fora" : "classes fora"} da banda` : "todas as classes na banda") : "defina alvos para medir o desvio"}
      tools={edit ? <>
        <span className={`small ${sum > 100.01 ? "neg" : "soft"}`}>soma {sum.toFixed(1).replace(".", ",")}%</span>
        <button className="btn sm" onClick={() => setEdit(null)}>Cancelar</button>
        <button className="btn primary sm" disabled={sum > 100.01 || invalid || save.isPending}
          onClick={() => save.mutate(Object.entries(edit).filter(([, v]) => v.trim() !== "").map(([k, v]) => ({ asset_class: k, target_pct: (parseBRL(v) ?? 0) / 100 })))}>Salvar</button>
      </> : <button className="btn sm" onClick={startEdit}>{d.alvos_definidos ? "Editar alvos" : "Definir alvos"}</button>}>
      <div className="bullets">
        {rows.map((r) => {
          const [label, tone] = STATUS[r.status] ?? [r.status, undefined];
          return (
            <div key={r.classe} className="bullet-row">
              <div className="bl-head"><span className="nm" title={r.classe}>{r.classe}</span>
                {!edit && <Chip tone={tone}>{label}</Chip>}</div>
              <div className="bullet" role="img" aria-label={`${r.classe}: ${pct(r.atual, 1)}${r.alvo !== null ? `, alvo ${pct(r.alvo, 1)}` : ""}`}>
                {r.min !== null && <span className="band" style={{ left: x(r.min), width: `calc(${x(r.max)} - ${x(r.min)})` }} />}
                <span className={`fill ${r.status}`} style={{ width: x(r.atual) }} />
                {r.alvo !== null && <span className="tick" style={{ left: x(r.alvo) }} />}
              </div>
              <div className="bl-vals">
                <span className="num strong">{pct(r.atual, 1)}</span>
                {edit ? <NumberInput width={64} min={0} max={100} placeholder="—" ariaLabel={`Alvo % de ${r.classe}`} value={edit[r.classe] ?? ""}
                  onChange={(v) => setEdit({ ...edit, [r.classe]: v })} />
                  : <span className="small soft">{r.alvo !== null ? `alvo ${pct(r.alvo, 0)}` : "—"}</span>}
                {!compact && !edit && r.ajuste_para_alvo !== null && Math.abs(r.ajuste_para_alvo) >= 1 &&
                  <span className="small">{r.ajuste_para_alvo > 0 ? "faltam " : "sobram "}<Money v={Math.abs(r.ajuste_para_alvo)} digits={0} /></span>}
              </div>
            </div>);
        })}
      </div>
      <div className="bullet-legend small soft"><span className="lg-fill" /> atual <span className="lg-band" /> banda <span className="lg-tick" /> alvo
        {d.reserva?.meses != null && <span style={{ marginLeft: "auto" }}>Reserva: {d.reserva.meses.toFixed(1).replace(".", ",")} meses de custo essencial (mínimo {d.reserva.minimo_meses})</span>}</div>
    </Panel>
  );
}
