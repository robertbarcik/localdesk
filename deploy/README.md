# Deploying LocalDesk on a tiny EC2 instance

One t3.small (2 GB RAM, ~23 USD/month all in) running Ubuntu 24.04 under the `mim-lab` AWS
profile (eu-central-1). The app runs under systemd on `127.0.0.1:7860`; Caddy sits in front and
provides HTTPS plus a password. Ollama runs on the box for the `nomic-embed-text` embeddings only.
The desk agent stays in cloud mode (OpenRouter), the minis and the voice orb on OpenAI, so the
server needs both API keys in `.env`.

No domain is needed: `sslip.io` turns the Elastic IP into a hostname and Caddy fetches a Let's
Encrypt certificate for it. HTTPS matters because the voice orb needs a secure origin for the
microphone.

Why t3.small and not t3.micro: Ollama with the embedding model, ChromaDB and the app do not fit
comfortably in 1 GB. `setup.sh` also adds a 2 GB swap file for pip and ingest peaks.

## Live deployment (since 2026-09-16)

| Item | Value |
|---|---|
| URL | https://18-198-245-243.sslip.io |
| Logins | `student` / `APP_PASSWORD` (participants), `robert` / `ADMIN_PASSWORD` (both in the local `.env`) |
| AWS profile / region | `mim-lab` / eu-central-1 |
| Instance | `i-0eaf4d11ccdcdfbba`, t3.small, 16 GB gp3, AMI `ubuntu-noble-24.04-amd64-server-20260904` |
| Elastic IP | `18.198.245.243` (`eipalloc-01ddddaceeb79e380`) |
| Security group | `sg-0d308e36a408b1c6c` (`localdesk`: 22, 80, 443 from anywhere) |
| Key pair | `localdesk` (private key `~/.ssh/localdesk-ec2` on Robert's Mac) |
| On the box | `/opt/localdesk` (owner `desk`), units `localdesk.service`, `ollama.service`, `caddy.service` |

## Files here

- `localdesk.service` — systemd unit, runs `python -m app.main` as the unprivileged `desk` user.
- `Caddyfile` — template: hostname, two `basicauth` users (bcrypt hashes), reverse proxy with
  `flush_interval -1` so the SSE chat stream reaches the browser token by token. WebSockets
  (`/ws`) pass through Caddy unchanged.
- `setup.sh` — idempotent host setup: swap, apt packages, Ollama + embedding model, venv, seed DB,
  ingest knowledge base, service, Caddy config.

## Recreate from scratch

```bash
export AWS_PROFILE=mim-lab AWS_DEFAULT_REGION=eu-central-1
# 1. ssh key (generated locally, public half imported; the private key never leaves the Mac)
ssh-keygen -t ed25519 -N "" -f ~/.ssh/localdesk-ec2
aws ec2 import-key-pair --key-name localdesk --public-key-material fileb://~/.ssh/localdesk-ec2.pub

# 2. security group in the default VPC
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name localdesk --description "LocalDesk demo" \
     --vpc-id $VPC --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions \
  'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=0.0.0.0/0}]' \
  'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]' \
  'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'

# 3. instance (latest Ubuntu 24.04 from Canonical, owner 099720109477) + Elastic IP
AMI=$(aws ec2 describe-images --owners 099720109477 \
      --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
      --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
ID=$(aws ec2 run-instances --image-id $AMI --instance-type t3.small --key-name localdesk \
     --security-group-ids $SG --metadata-options HttpTokens=required \
     --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=16,VolumeType=gp3}' \
     --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=localdesk}]' \
     --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --instance-ids $ID
ALLOC=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id $ID --allocation-id $ALLOC
IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC --query 'Addresses[0].PublicIp' --output text)

# 4. code + secrets, then the setup script (HOST = IP with dots replaced by dashes + .sslip.io)
#    .env needs OPENROUTER_API_KEY, OPENAI_API_KEY, APP_PASSWORD, ADMIN_PASSWORD
ssh -i ~/.ssh/localdesk-ec2 ubuntu@$IP 'sudo mkdir -p /opt/localdesk && sudo chown ubuntu /opt/localdesk'
rsync -az -e "ssh -i ~/.ssh/localdesk-ec2" --exclude venv --exclude .venv --exclude .git --exclude .env \
  --exclude vectorstore --exclude logs --exclude 'data/db/*.db*' --exclude __pycache__ --exclude .DS_Store \
  ./ ubuntu@$IP:/opt/localdesk/
scp -i ~/.ssh/localdesk-ec2 .env ubuntu@$IP:/opt/localdesk/.env
ssh -i ~/.ssh/localdesk-ec2 ubuntu@$IP "sudo HOST=${IP//./-}.sslip.io bash /opt/localdesk/deploy/setup.sh"
```

## Day-to-day

```bash
# update the code after a change (rsync + restart; setup.sh is safe to re-run too,
# and re-running it re-seeds the DB and re-ingests the KB)
rsync -az -e "ssh -i ~/.ssh/localdesk-ec2" --exclude venv --exclude .venv --exclude .git --exclude .env \
  --exclude vectorstore --exclude logs --exclude 'data/db/*.db*' --exclude __pycache__ --exclude .DS_Store \
  ./ ubuntu@18.198.245.243:/opt/localdesk/
ssh -i ~/.ssh/localdesk-ec2 ubuntu@18.198.245.243 'sudo systemctl restart localdesk'

# logs / health
ssh -i ~/.ssh/localdesk-ec2 ubuntu@18.198.245.243 'sudo journalctl -u localdesk -n 50 --no-pager'
curl -s -u robert:$ADMIN_PASSWORD https://18-198-245-243.sslip.io/api/status | jq

# what participants spent (per role and model, from the app's own cost table)
ssh -i ~/.ssh/localdesk-ec2 ubuntu@18.198.245.243 \
  "sqlite3 /opt/localdesk/data/db/localdesk.db 'select role,model,round(sum(cost_usd),4) from request_metrics group by 1,2'"

# pause between courses (instance stops; volume + Elastic IP keep costing ~5 USD/month)
aws ec2 stop-instances  --profile mim-lab --instance-ids i-0eaf4d11ccdcdfbba
aws ec2 start-instances --profile mim-lab --instance-ids i-0eaf4d11ccdcdfbba   # same IP, same URL

# tear down completely (then delete the key pair + ~/.ssh/localdesk-ec2 if it is not coming back)
aws ec2 terminate-instances --profile mim-lab --instance-ids i-0eaf4d11ccdcdfbba
aws ec2 wait instance-terminated --profile mim-lab --instance-ids i-0eaf4d11ccdcdfbba
aws ec2 release-address    --profile mim-lab --allocation-id eipalloc-01ddddaceeb79e380
aws ec2 delete-security-group --profile mim-lab --group-id sg-0d308e36a408b1c6c
```

## Notes

- Change a password: edit `APP_PASSWORD` / `ADMIN_PASSWORD` in the server's `.env`, re-run
  `setup.sh` (or just the Caddy block of it).
- Everyone shares one ops room: conversation memory is in-process and the simulation and sentinel
  are global. Fine for one or two participants at a time.
- Spend: text chat is fractions of a cent per run; the voice orb bills about 0.05 USD per minute
  of gpt-live-1 session on the OpenAI account; a running simulation calls the sentinel every 25 s.
  Set spend caps on OpenRouter and OpenAI before handing out the `student` login, rotate the
  password after each course.
- Port 22 is open to the world for convenience; narrow it to your IP in the security group if
  the box stays up for long.
- `config.yaml` on the server is the repo copy (`server.host: 0.0.0.0`); port 7860 is not in the
  security group, so only Caddy can reach it from outside.
