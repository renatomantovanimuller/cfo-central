# CFO Central na nuvem: Oracle Always Free + Tailscale

O app roda 24/7 numa VM gratuita da Oracle e só é acessível pela sua **tailnet** (a rede privada do Tailscale).
Nenhuma porta fica aberta na internet; o navegador recebe HTTPS com certificado válido da própria tailnet.

```
celular / notebook (app Tailscale)                       VM Oracle · Ubuntu 24.04 ARM · 2 OCPU · 12 GB
  https://cfo-central.<tailnet>.ts.net ──WireGuard──▶  tailscale serve :443 ─▶ 127.0.0.1:8060
                                                          ├─ app   FastAPI + agendador (sync 4/4 h, mercado 19h45, e-mails)
                                                          ├─ db    Postgres 16 (sem porta no host)
                                                          └─ backup pg_dump diário conferido (21 dias)
Claude Desktop / Claude Code (PC) ──ssh pela tailnet──▶  docker exec cfo-central-app-1 python -m app.assistant.mcp_server
Saída da VM: Pluggy, BCB, Yahoo, Gmail (587). Entrada: nenhuma (a regra da porta 22 é removida no passo 4).
```

Custo: **zero** dentro do Always Free (1 VM A1 de 2 OCPU/12 GB, ~50 GB de disco, 20 GB de Object Storage).
Em 2026 a Oracle reduziu o Always Free de 4 OCPU/24 GB para 2 OCPU/12 GB; o CFO Central usa menos de 2 GB.

## Passo a passo (uma vez)

**0. Tailscale** (painel em login.tailscale.com)
- *DNS*: ligue **MagicDNS** e **HTTPS Certificates**.
- *Settings → Keys → Generate auth key* (sem "Reusable"). Copie a chave `tskey-auth-…`.

**1. Conta Oracle** em oracle.com/cloud/free (pede cartão só para verificar).
- *Home region*: **Brazil East (São Paulo)**. Não dá para trocar depois e o Always Free só vale nela.
- Recomendado: *Upgrade to Pay As You Go* e um *Budget* com alerta de US$ 1. Continua custando zero dentro dos
  limites e evita duas armadilhas do Always Free puro: VM ociosa recuperada pela Oracle e falta de capacidade A1.

**2. Criar a VM** (*Compute → Instances → Create instance*)
- *Image*: Canonical Ubuntu 24.04 (aarch64). *Shape*: `VM.Standard.A1.Flex`, **2 OCPU, 12 GB**.
- *Networking*: VCN/subnet pública padrão, com IP público (usado só para saída).
- *SSH keys*: "Generate a key pair" e baixe a chave privada. Salve como `C:\Users\renat\.ssh\cfo-central.key`.
- *Boot volume*: 50 GB.
- *Show advanced options → Management → cloud-init*: cole `deploy/cloud-init.yaml` trocando
  `COLE_AQUI_A_AUTH_KEY` pela chave do passo 0.
- "Out of capacity": tente outro *availability domain* ou mais tarde (comum no A1).

**3. Tailscale da VM.** Em ~5 minutos a máquina `cfo-central` aparece em *Machines*. No menu dela:
**Disable key expiry** (senão o acesso cai em 180 dias).

**4. Fechar a internet.** *Networking → Virtual cloud networks → (sua VCN) → Security Lists → Default* →
apague a regra de entrada `0.0.0.0/0 TCP 22`. A partir daqui a VM só é vista pela tailnet.

**5. SSH pelo Tailscale no PC.** Proteja a chave e crie `C:\Users\renat\.ssh\config`:
```powershell
icacls $env:USERPROFILE\.ssh\cfo-central.key /inheritance:r /grant:r "$($env:USERNAME):R"
```
```
Host cfo-central
  HostName cfo-central
  User ubuntu
  IdentityFile ~/.ssh/cfo-central.key
```
Teste com `ssh cfo-central` (aceite a impressão digital na primeira vez).

**6. Levar para a nuvem.** Com o CFO Central rodando no PC (`INICIAR.bat`), dê dois cliques em
**`NUVEM-LEVAR.bat`**. Ele exporta o banco, envia código, `.env` e curadoria, restaura o banco na VM, sobe o app
e liga o HTTPS. No fim mostra o endereço `https://cfo-central.<tailnet>.ts.net`.

**7. Usar.** Instale o Tailscale no celular (mesma conta) e abra o endereço. O login do app continua valendo.

**8. Desligar o PC da jogada.** `PARAR.bat` no PC (duas instâncias sincronizando mandariam e-mail em dobro).
Para o Claude usar a nuvem: `powershell -ExecutionPolicy Bypass -File deploy\instalar-mcp-remoto.ps1` e reabra o
Claude Desktop. A tarefa do fechamento mensal continua funcionando do mesmo jeito.

## Depois

- **Atualizar o código**: `NUVEM-PUBLICAR.bat` (envia o código e reconstrói; o banco fica).
- **Logs**: `ssh cfo-central "cd /opt/cfo-central && docker compose logs --tail 100 app"`.
- **Backups**
  - Na VM: diário em `/opt/cfo-central/backups`, conferido com `pg_restore --list` antes de valer
    (`ULTIMO-BACKUP.txt` diz se o último deu certo). Corrige o problema dos dumps de 0 byte do PC.
  - Cópia no PC: agende `deploy\puxar-backup.ps1` no Agendador de Tarefas (diário, "executar assim que possível").
  - Cópia cifrada no Object Storage da Oracle (opcional, recomendado):
    1. Na VM: `age-keygen -o chave.txt`; guarde o conteúdo no seu gerenciador de senhas; anote a linha
       `public key: age1…`; `shred -u chave.txt`. A chave privada **nunca** fica na VM.
    2. Oracle: crie o bucket `cfo-backups` (*Storage → Buckets*) e uma *Customer Secret Key* (Perfil → Customer secret keys).
    3. Na VM: `rclone config` → novo remote `oci`, tipo *S3*, provedor *Other*, endpoint
       `https://<namespace>.compat.objectstorage.sa-saopaulo-1.oraclecloud.com`, região `sa-saopaulo-1`.
    4. `/opt/cfo-central/deploy/backup-offsite.env`:
       `AGE_RECIPIENT=age1…`, `RCLONE_REMOTE=oci:cfo-backups`, `KEEP_DAYS=60`; rode `deploy/setup-vm.sh` de novo.
    5. Restaurar: baixe o `.age`, `age -d -i chave.txt arquivo.dump.age > cfo.dump`, `pg_restore`.
- **Webhooks da Pluggy** (opcional; o app já relê a cada 4 h e o MeuPluggy atualiza 1×/dia): só a rota do webhook
  pode ser pública, com `sudo tailscale funnel --bg --set-path /api/webhooks/pluggy http://127.0.0.1:8060/api/webhooks/pluggy`
  e `PUBLIC_URL=https://cfo-central.<tailnet>.ts.net` no `.env`. O webhook só dispara releitura; não grava dados.

## Segurança

- Sem porta aberta na internet; acesso só por aparelhos da sua tailnet (WireGuard) e HTTPS de ponta a ponta.
- O login do app continua (argon2; cookie `HttpOnly`, `SameSite=strict` e `Secure` na nuvem).
- Segredos (Pluggy, Gmail, `SECRET_KEY`) só no `/opt/cfo-central/.env` da VM, com permissão 600. O disco é
  cifrado em repouso pela Oracle, mas a Oracle, como provedora, tem acesso à infraestrutura: é o custo de sair do PC.
- Atualizações de segurança do Ubuntu automáticas (`unattended-upgrades`).
- Reforços opcionais no Tailscale: ACL liberando a VM só para o seu usuário; *Tailnet Lock*.
- Se algum segredo vazar: troque no painel de origem (Pluggy/Google), edite o `.env` na VM e rode `deploy/setup-vm.sh`.

## Riscos conhecidos

- **Capacidade A1** às vezes esgotada na criação da VM (passo 2).
- **Ociosidade**: em conta Always Free pura, a Oracle pode parar VMs com uso muito baixo por 7 dias. O upgrade para
  Pay As You Go (passo 1) remove esse risco sem custo dentro dos limites.
- **Yahoo** pode limitar requisições vindas de IPs de nuvem. Se acontecer, a página Saúde dos dados acusa cotação
  atrasada; BCB e Pluggy não são afetados.
