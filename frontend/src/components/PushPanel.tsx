import { useQuery } from "@tanstack/react-query";
import { BellRing, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useApiMutation } from "../hooks/useApiMutation";
import { dateTime } from "../format";
import { currentSubscription, endpointId, isIOS, isStandalone, pushSupported, subscribeThisDevice, unsubscribeThisDevice } from "../push";
import { Chip, Panel, useToast } from "./ui";

const guessName = () => (isIOS() ? "iPhone" : /Android/.test(navigator.userAgent) ? "Celular Android" : "Este computador");

/** Notificações no celular (Web Push): o mesmo conteúdo dos alertas por e-mail, direto na tela de bloqueio. */
export function PushPanel({ hour }: { hour?: number }) {
  const q = useQuery({ queryKey: ["push"], queryFn: () => api<any>("/api/push") });
  const toast = useToast();
  const [mine, setMine] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const supported = pushSupported();
  useEffect(() => { currentSubscription().then(async (s) => setMine(s ? await endpointId(s.endpoint) : null)).catch(() => setMine(null)); }, [q.data]);
  const test = useApiMutation({ mutationFn: () => api<any>("/api/push/test", { method: "POST" }), invalidate: [["push"]],
    onSuccess: (r) => toast(r.ok ? `Teste enviado para ${r.enviados} aparelho(s)` : `Falhou: ${r.erro ?? r.erros.join("; ")}`, !r.ok) });
  const remove = useApiMutation({ mutationFn: (id: string) => (id === mine ? unsubscribeThisDevice(id) : api(`/api/push/subscribe/${id}`, { method: "DELETE" })),
    invalidate: [["push"]], successMessage: "Aparelho removido" });

  const activate = async () => {
    setBusy(true);
    try { await subscribeThisDevice(q.data.public_key, guessName()); toast("Notificações ativadas neste aparelho"); q.refetch(); }
    catch (e) { toast(e instanceof Error ? e.message : "Não foi possível ativar", true); }
    finally { setBusy(false); }
  };
  const devices: any[] = q.data?.aparelhos ?? [];
  const here = devices.some((d) => d.id === mine);

  return (
    <Panel title="Notificações no celular" hint="alertas graves, fechamento do mês e avisos, na tela de bloqueio">
      {!supported ? (
        <p className="note" style={{ marginTop: 0 }}>Este navegador não aceita notificações aqui. Abra o CFO Central pelo endereço do Tailscale
          (https://…ts.net) no celular{isIOS() ? ", no Safari, e instale na Tela de Início" : ""}.</p>
      ) : isIOS() && !isStandalone() ? (
        <p className="note" style={{ marginTop: 0 }}>No iPhone, as notificações só funcionam com o app instalado: toque em Compartilhar ›
          Adicionar à Tela de Início, abra pelo ícone e volte aqui.</p>
      ) : here ? (
        <p style={{ margin: 0 }}><Chip tone="green">ativo neste aparelho</Chip>{" "}
          <button className="btn sm" onClick={() => test.mutate()} disabled={test.isPending}>Enviar teste</button></p>
      ) : (
        <p style={{ margin: 0 }}><button className="btn primary" onClick={activate} disabled={busy || !q.data}><BellRing size={15} /> Ativar neste aparelho</button>
          {devices.length > 0 && <>{" "}<button className="btn sm ghost" onClick={() => test.mutate()} disabled={test.isPending}>Enviar teste aos aparelhos</button></>}</p>
      )}

      {devices.length > 0 && <table className="table" style={{ marginTop: 10 }}><tbody>{devices.map((d) => (
        <tr key={d.id}><td>{d.nome}{d.id === mine && <span className="small soft"> (este)</span>}<div className="small soft">{d.origem}</div></td>
          <td className="small soft">desde {dateTime(d.criado_em)}</td>
          <td>{d.ultimo_erro ? <Chip tone="red">falhou</Chip> : d.ultimo_ok ? <Chip tone="green">entregue {dateTime(d.ultimo_ok)}</Chip> : <span className="small soft">sem envio ainda</span>}</td>
          <td><button className="btn ghost sm danger" aria-label={`Remover ${d.nome}`} onClick={() => remove.mutate(d.id)}><Trash2 size={14} /></button></td></tr>))}</tbody></table>}

      <p className="note">Vai para o celular: alertas graves e de atenção (resumo às {hour ?? 8}h), o fechamento do mês no dia 1 e avisos como
        conector novo de benefício. A mensagem sai cifrada do seu PC para o serviço de push do celular (Google ou Apple), que só a entrega.</p>
    </Panel>
  );
}
