#!/bin/sh
# Backup diário do Postgres, conferido antes de entrar no lugar (roda no serviço "backup" do docker compose).
# pg_dump vai para um arquivo temporário; só vira cfo-AAAAMMDD-HHMM.dump se tiver conteúdo e o pg_restore
# conseguir ler o índice. Falha não deixa arquivo vazio: tenta de novo em 1 hora.
set -u
KEEP_DAYS="${KEEP_DAYS:-30}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
RETRY="${BACKUP_RETRY_SECONDS:-3600}"
while true; do
  ts=$(date +%Y%m%d-%H%M)
  tmp="/backups/.cfo-$ts.dump.part"
  final="/backups/cfo-$ts.dump"
  if pg_dump -h db -U cfo -d cfo -Fc -f "$tmp" && [ -s "$tmp" ] && pg_restore --list "$tmp" >/dev/null 2>&1; then
    mv "$tmp" "$final"
    echo "backup ok: $final ($(wc -c < "$final") bytes)"
    echo "$ts ok $(wc -c < "$final")" > /backups/ULTIMO-BACKUP.txt
    find /backups -name 'cfo-*.dump' -mtime +"$KEEP_DAYS" -delete
    wait_s="$INTERVAL"
  else
    echo "backup FALHOU em $ts" >&2
    echo "$ts FALHOU" > /backups/ULTIMO-BACKUP.txt
    rm -f "$tmp"
    wait_s="$RETRY"
  fi
  find /backups -name 'cfo-*.dump' -size 0 -delete  # restos vazios da versão antiga do script
  sleep "$wait_s"
done
