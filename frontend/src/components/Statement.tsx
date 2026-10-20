import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { acct, monthLabel, pct } from "../format";

export type StmtRow = {
  key: string; label: string; values: Record<string, number | null>; total?: number | null; subtotal?: boolean; final?: boolean;
  av?: Record<string, number | null>; children?: StmtRow[]; id?: string; italic?: boolean; percent?: boolean;
};

export function Statement({ months, rows, showAv, onCell, totalCol = true }:
  { months: string[]; rows: StmtRow[]; showAv?: boolean; onCell?: (row: StmtRow, month: string | null) => void; totalCol?: boolean }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const flip = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));

  const render = (r: StmtRow, depth: number, path: string): JSX.Element => {
    const k = `${path}/${r.key}`;
    const has = (r.children?.length ?? 0) > 0;
    const cls = [r.subtotal ? "sub" : "", r.final ? "final" : "", depth === 1 ? "l1" : depth >= 2 ? "l2" : ""].join(" ");
    const tint = (v: number | null | undefined) => (!r.subtotal || r.percent || v === null || v === undefined ? "" : v < 0 ? "neg" : r.final && v > 0 ? "pos" : "");
    const fmt = (v: number | null | undefined) => (r.percent ? pct(v ?? null, 0) : acct(v ?? null));
    return (
      <Fragment key={k}>
        <tr className={cls}>
          <td style={{ fontStyle: r.italic ? "italic" : undefined }}>
            {has ? <button className="toggle" onClick={() => flip(k)} aria-label={open[k] ? "Recolher" : "Expandir"}>
              {open[k] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button> : <span style={{ display: "inline-block", width: 18 }} />}
            {r.subtotal && "= "}{r.label}
          </td>
          {months.map((m) => {
            const v = r.values[m];
            return (
              <td key={m} className={`num ${onCell && !r.subtotal && !r.percent ? "cell" : ""} ${tint(v)}`}
                onClick={() => onCell && !r.subtotal && !r.percent && onCell(r, m)}>
                {fmt(v)}
                {showAv && r.av && r.av[m] !== null && r.av[m] !== undefined && <span className="av">{pct(r.av[m], 0)}</span>}
              </td>
            );
          })}
          {totalCol && <td className={`num total-col ${tint(r.total)}`}>{r.percent ? "" : acct(r.total ?? null)}</td>}
        </tr>
        {has && open[k] && r.children!.map((c) => render(c, depth + 1, k))}
      </Fragment>
    );
  };

  return (
    <div className="table-wrap" style={{ maxHeight: "none" }}>
      <table className="stmt">
        <thead><tr><th>Linha</th>{months.map((m) => <th key={m}>{monthLabel(m)}</th>)}{totalCol && <th className="total-col">Total</th>}</tr></thead>
        <tbody>{rows.map((r) => render(r, 0, ""))}</tbody>
      </table>
    </div>
  );
}
