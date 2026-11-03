#!/usr/bin/env bash
# Sobe ou atualiza o CFO Central na VM: build da imagem, migrações (no start do app), HTTPS pela tailnet e
# backup externo opcional. Idempotente: rode de novo a cada atualização de código.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml"
[ -f .env ] || { echo "Falta o .env em $(pwd). Rode deploy/levar-para-nuvem.ps1 no PC."; exit 1; }
chmod 600 .env
grep -q '^COOKIE_SECURE=' .env || echo 'COOKIE_SECURE=true' >> .env
mkdir -p backups curadoria
chmod +x deploy/*.sh
$COMPOSE up -d --build --remove-orphans
echo "Aguardando o app..."
for _ in $(seq 1 120); do curl -fsS http://127.0.0.1:8060/api/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8060/api/health >/dev/null || { $COMPOSE logs --tail 60 app; exit 1; }
# HTTPS com certificado da tailnet (precisa de MagicDNS e "HTTPS Certificates" ligados no painel do Tailscale)
sudo tailscale serve --bg --https=443 http://127.0.0.1:8060 >/dev/null
if [ -f deploy/backup-offsite.env ]; then
  sudo install -m 644 deploy/systemd/cfo-backup-offsite.service /etc/systemd/system/
  sudo install -m 644 deploy/systemd/cfo-backup-offsite.timer /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now cfo-backup-offsite.timer
fi
docker image prune -f >/dev/null
name=$(tailscale status --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
echo "Pronto: https://$name (só abre em aparelhos da sua tailnet)"
