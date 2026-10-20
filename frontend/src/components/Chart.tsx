import ReactECharts from "echarts-for-react";
import { useMemo } from "react";
import { isPrivate, MASK, usePrivacy } from "../privacy";

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Paleta derivada dos tokens: tinta verde, azul, ocre, ardósia, vermelho e variações. */
export function palette() {
  return [cssVar("--ledger"), cssVar("--blue"), cssVar("--ochre"), cssVar("--slate"), cssVar("--debit"),
    "#5f8f7f", "#8a6fb0", "#3f8fa6", "#a3785a", "#7a8c3c"];
}

export function baseOption() {
  const ink2 = cssVar("--ink-2"), rule = cssVar("--rule"), sheet = cssVar("--sheet"), ink = cssVar("--ink");
  return {
    color: palette(),
    textStyle: { fontFamily: "Archivo, system-ui, sans-serif", color: ink2 },
    grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
    tooltip: { backgroundColor: sheet, borderColor: rule, textStyle: { color: ink }, confine: true },
    legend: { textStyle: { color: ink2 }, icon: "roundRect", itemWidth: 12, itemHeight: 8, top: 0 },
    xAxis: { axisLine: { lineStyle: { color: rule } }, axisTick: { show: false }, axisLabel: { color: ink2 }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, splitLine: { lineStyle: { color: rule } }, axisLabel: { color: ink2 } },
  };
}

/** Eixo de valores em pt-BR: 2,5 mil / 1,2 mi. Oculta os valores no modo privacidade. */
export const kTick = (v: number) => {
  if (isPrivate()) return MASK;
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  const fmt = (x: number, unit: string) => `${sign}${x.toFixed(1).replace(/\.0$/, "").replace(".", ",")} ${unit}`;
  return a >= 1e6 ? fmt(a / 1e6, "mi") : a >= 1e3 ? fmt(a / 1e3, "mil") : `${sign}${Math.round(a)}`;
};

/** Mantém a cor da legenda (itemStyle) igual à da série (lineStyle), sem alterar o objeto original. */
function syncSeriesColor(s: any) {
  const lineColor = s?.lineStyle?.color;
  if (!lineColor || s.itemStyle?.color) return s;
  return { ...s, itemStyle: { ...(s.itemStyle ?? {}), color: lineColor } };
}

/** Tooltip do modo privacidade: nomes e percentuais visíveis, valores ocultos. */
function maskedTooltip(params: any) {
  const items = Array.isArray(params) ? params : [params];
  const head = items[0]?.axisValueLabel ?? (items.length === 1 ? "" : items[0]?.name ?? "");
  const rows = items.map((i: any) => `${i.marker ?? ""}${i.seriesName || i.name}: ${i.percent !== undefined ? `${String(i.percent).replace(".", ",")}%` : MASK}`);
  return [head, ...rows].filter(Boolean).join("<br/>");
}

export function Chart({ option, height = 260, onClick }: { option: any; height?: number; onClick?: (p: any) => void }) {
  const hidden = usePrivacy();
  const merged = useMemo(() => {
    const b = baseOption();
    const maskAxis = (a: any) => (hidden && a?.type === "value" ? { ...a, axisLabel: { ...(a?.axisLabel ?? {}), formatter: () => MASK } } : a);
    const maskTip = (t: any) => (hidden ? { ...t, valueFormatter: undefined, formatter: maskedTooltip } : t);
    return {
      ...b, ...option,
      xAxis: Array.isArray(option.xAxis) ? option.xAxis.map((x: any) => maskAxis({ ...b.xAxis, ...x })) : option.xAxis ? maskAxis({ ...b.xAxis, ...option.xAxis }) : undefined,
      yAxis: Array.isArray(option.yAxis) ? option.yAxis.map((y: any) => maskAxis({ ...b.yAxis, ...y })) : option.yAxis ? maskAxis({ ...b.yAxis, ...option.yAxis }) : undefined,
      tooltip: maskTip({ ...b.tooltip, ...(option.tooltip ?? {}) }),
      legend: option.legend === false ? undefined : { ...b.legend, ...(option.legend ?? {}) },
      grid: { ...b.grid, ...(option.grid ?? {}) },
      series: Array.isArray(option.series) ? option.series.map(syncSeriesColor) : option.series,
    };
  }, [option, hidden]);
  return (
    <ReactECharts option={merged} style={{ height, width: "100%" }} notMerge lazyUpdate
      onEvents={onClick ? { click: onClick } : undefined} opts={{ renderer: "svg" }} />
  );
}
