#!/usr/bin/env bash
# Leva o backup mais recente para fora da VM, cifrado com age (só quem tem a chave privada abre).
# Configuração em deploy/backup-offsite.env (ver deploy/README.md):
#   AGE_RECIPIENT=age1...            chave PÚBLICA (a privada fica no seu gerenciador de senhas, nunca na VM)
#   RCLONE_REMOTE=oci:cfo-backups    destino S3-compatível configurado no rclone (Object Storage da Oracle etc.)
#   KEEP_DAYS=60
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source deploy/backup-offsite.env
f=$(ls -1t backups/cfo-*.dump 2>/dev/null | head -1 || true)
[ -n "${f:-}" ] && [ -s "$f" ] || { echo "Nenhum backup válido em backups/"; exit 1; }
out="/tmp/$(basename "$f").age"
age -r "$AGE_RECIPIENT" -o "$out" "$f"
rclone --config /home/ubuntu/.config/rclone/rclone.conf copyto "$out" "$RCLONE_REMOTE/$(basename "$out")"
rm -f "$out"
rclone --config /home/ubuntu/.config/rclone/rclone.conf delete --min-age "${KEEP_DAYS:-60}d" "$RCLONE_REMOTE" || true
echo "Enviado: $(basename "$out")"
