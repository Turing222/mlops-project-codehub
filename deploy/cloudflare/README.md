# Cloudflare Tunnel (API edge)

Dewflow production uses **split-origin** delivery:

- Frontend: Cloudflare Pages (`https://app.<domain>`)
- API: Cloudflare Tunnel → EC2 `api-nginx` on `http://127.0.0.1:8081` (`https://api.<domain>`)

Tunnel setup is **not** part of `deploy/docker-compose.yml`. Credentials and tokens stay on the EC2 host or in Cloudflare — never commit them.

## Files in this directory

| File | Purpose |
|------|---------|
| `cloudflared.config.yml.example` | Ingress template (`api.<domain>` → loopback 8081) |
| `cloudflared.service.example` | systemd unit template |

Domain alignment across EC2, Pages, and GitHub: [../domains.env.example](../domains.env.example).

Full first-deploy checklist: [../CHECKLIST.md](../CHECKLIST.md).

## One-time setup (CLI)

Run on the EC2 host after `make deploy-ec2-wait` succeeds against `http://127.0.0.1:8081`.

### 1. Install cloudflared

Follow [Cloudflare's install docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) for your OS (package repo or binary).

### 2. Authenticate and create a tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create dewflow-api
```

Note the tunnel UUID from the output. Credentials are written under `~/.cloudflared/<UUID>.json`.

### 3. Route DNS

```bash
cloudflared tunnel route dns dewflow-api api.<domain>
```

Or create the public hostname in the Cloudflare Zero Trust dashboard with the same target.

### 4. Install config and service

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/<TUNNEL_UUID>.json /etc/cloudflared/
sudo cp deploy/cloudflare/cloudflared.config.yml.example /etc/cloudflared/config.yml
# Edit /etc/cloudflared/config.yml: replace <TUNNEL_UUID> and api.<domain>
sudo cp deploy/cloudflare/cloudflared.service.example /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared
```

### 5. Verify public API

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://api.<domain>/api/v1/health_check/live
curl -sS -o /dev/null -w '%{http_code}\n' https://api.<domain>/api/v1/health_check/db_ready
```

Both should return `200`. Then set `DEPLOY_BASE_URL=https://api.<domain>` in `deploy/.env.ec2` and re-run `make deploy-ec2-wait`.

## Security notes

- Keep `API_NGINX_BIND=127.0.0.1` in `deploy/.env.ec2`. Do not expose port 8081 on a public security group.
- Only trust `CF-Connecting-IP` when traffic enters through Tunnel / a trusted edge, not when `api-nginx` is reachable directly from the internet.
- See [docs/platform/deploy-ec2.md](../../docs/platform/deploy-ec2.md) for rate-limit proxy CIDR settings.
