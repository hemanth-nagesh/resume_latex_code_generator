# LaTeX → PDF MCP Server

A fully-hosted, accessible **MCP server** that compiles LaTeX source code into PDF documents.  
Built with **FastMCP** (Python) + **TeX Live** + **FastAPI**, deployed on **Azure Student VM**.

> **Live at:** `http://20.212.83.231` | Region: `southeastasia` | VM: `Standard_B2s_v2`

---

## 🏗️ Project Structure

```
latex-mcp-server/
├── app/
│   ├── main.py            # FastMCP server + REST API endpoints
│   ├── auth.py            # X-API-Key authentication middleware
│   └── latex_service.py   # LaTeX → PDF compilation engine
├── nginx/
│   └── nginx.conf         # Reverse proxy with rate limiting + SSE support
├── scripts/
│   ├── setup_azure.sh     # One-time Azure VM setup (Docker, swap, firewall)
│   ├── azure_cli_steps.sh # Step-by-step Azure CLI provisioning guide
│   └── deploy.sh          # Update & redeploy script
├── examples/
│   └── agent_usage.py     # How other agents call this server
├── Dockerfile             # Multi-stage image with TeX Live
├── docker-compose.yml     # App + Nginx orchestration
├── .env.example           # Environment variable template
├── requirements.txt       # Python dependencies
└── README.md
```

---

## 🚀 Deployment Guide (Azure CLI — Step by Step)

This guide uses **Azure CLI** to provision everything from your terminal. Each step is in [`scripts/azure_cli_steps.sh`](scripts/azure_cli_steps.sh).

### Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- Azure for Students subscription activated
- SSH key generated

### Step 1 — Login

```bash
az login
az account show --output table    # confirm "Azure for Students"
```

### Step 2 — Set Variables

```bash
RESOURCE_GROUP="latex-mcp-rg"
LOCATION="southeastasia"         # student-friendly region
VM_NAME="latex-mcp-vm"
VM_SIZE="Standard_B2s_v2"       # 2 vCPU, 4GB RAM
OS_IMAGE="Ubuntu2204"
ADMIN_USER="azureuser"
NSG_NAME="latex-mcp-nsg"
PUBLIC_IP_NAME="latex-mcp-ip"
VNET_NAME="latex-mcp-vnet"
SSH_KEY_PATH="$HOME/.ssh/latex_mcp_key"
```

### Step 3 — Generate SSH Key

```bash
ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -C "latex-mcp-azure" -N ""
```

### Step 4 — Create Resource Group

```bash
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
```

### Step 5 — Create Network + Subnet

```bash
az network vnet create \
    --resource-group "$RESOURCE_GROUP" --name "$VNET_NAME" \
    --address-prefix "10.0.0.0/16" --subnet-name "default" \
    --subnet-prefix "10.0.0.0/24" --location "$LOCATION"
```

### Step 6 — Create NSG + Firewall Rules

```bash
az network nsg create --resource-group "$RESOURCE_GROUP" --name "$NSG_NAME"
az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" \
    --name "AllowSSH" --priority 100 --protocol Tcp --destination-port-range 22 --access Allow
az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" \
    --name "AllowHTTP" --priority 110 --protocol Tcp --destination-port-range 80 --access Allow
az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" \
    --name "AllowHTTPS" --priority 120 --protocol Tcp --destination-port-range 443 --access Allow
```

### Step 7 — Create Static Public IP

```bash
az network public-ip create --resource-group "$RESOURCE_GROUP" --name "$PUBLIC_IP_NAME" \
    --location "$LOCATION" --allocation-method Static --sku Standard
PUBLIC_IP=$(az network public-ip show --resource-group "$RESOURCE_GROUP" \
    --name "$PUBLIC_IP_NAME" --query "ipAddress" --output tsv)
echo "Public IP: $PUBLIC_IP"
```

### Step 8 — Create VM

```bash
az vm create --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
    --size "$VM_SIZE" --image "$OS_IMAGE" --admin-username "$ADMIN_USER" \
    --ssh-key-values "${SSH_KEY_PATH}.pub" --vnet-name "$VNET_NAME" \
    --subnet "default" --nsg "$NSG_NAME" --public-ip-address "$PUBLIC_IP_NAME" \
    --os-disk-size-gb 64 --storage-sku Premium_LRS --location "$LOCATION"
```

### Step 9 — Add SSH Config Shortcut

```bash
cat >> ~/.ssh/config << EOF

# Azure LaTeX MCP Server
Host latex-mcp
    HostName $PUBLIC_IP
    User $ADMIN_USER
    IdentityFile $SSH_KEY_PATH
    ServerAliveInterval 60
EOF
```

### Step 10 — Upload & Setup

```bash
# Upload project
scp -i "$SSH_KEY_PATH" -r ./latex-mcp-server "azureuser@$PUBLIC_IP:/home/azureuser/latex-mcp-server"

# SSH in and run setup
ssh latex-mcp
sudo mv ~/latex-mcp-server /opt/latex-mcp
sudo chown -R azureuser:azureuser /opt/latex-mcp
cd /opt/latex-mcp
sudo ./scripts/setup_azure.sh
```

### Step 11 — Configure `.env`

```bash
cd /opt/latex-mcp
API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "Your API key: $API_KEY"

cat > .env << EOF
API_KEYS=${API_KEY}
PUBLIC_BASE_URL=http://$PUBLIC_IP
PDF_OUTPUT_DIR=/app/output
LOG_LEVEL=INFO
EOF
```

### Step 12 — Build & Start

```bash
docker compose up -d --build
```

> ⚠️ First build takes 5–10 minutes (downloading TeX Live ~1GB).

### Step 13 — Verify

```bash
curl http://$PUBLIC_IP/health
# {"status": "ok", "pdflatex_available": true, ...}

curl -X POST http://$PUBLIC_IP/api/convert \
    -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" \
    -d '{"latex_source":"\\documentclass{article}\n\\begin{document}\nHello!\n\\end{document}","filename":"test"}'
```

---

## 🔌 Using as MCP (for Claude, Antigravity, Cursor, etc.)

### MCP Config

Add this to your agent's `mcpServers` configuration:

```json
{
  "mcpServers": {
    "latex-pdf": {
      "url": "http://20.212.83.231/mcp",
      "transport": "streamable-http",
      "headers": {
        "X-API-Key": "MK0RnFn4bA2sDYmW_3LaM7soIZKierR0qQKCLfvK3f8"
      }
    }
  }
}
```

Once connected, your agent gains three tools:

| Tool | Description |
|------|-------------|
| `compile_latex_tool` | Compile LaTeX source → PDF (base64) |
| `list_pdfs_tool` | List all PDFs on the server |
| `server_info_tool` | Server status, version, uptime |

### Example: Compiling a Document via MCP

```python
# pip install mcp
import asyncio, json
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def compile_via_mcp():
    async with streamablehttp_client("http://20.212.83.231/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("compile_latex_tool", arguments={
                "latex_source": r"\documentclass{article}\begin{document}Hello MCP!\end{document}",
                "filename": "mcp_example"
            })

            data = json.loads(result.content[0].text)
            print(f"✅ {data['filename']} — {data['size_bytes']} bytes")

asyncio.run(compile_via_mcp())
```

### Example: REST API (no MCP SDK needed)

```bash
curl -X POST http://20.212.83.231/api/convert \
  -H "Content-Type: application/json" \
  -H "X-API-Key: MK0RnFn4bA2sDYmW_3LaM7soIZKierR0qQKCLfvK3f8" \
  -d '{"latex_source":"\\documentclass{article}\n\\begin{document}\nHello!\n\\end{document}","filename":"test"}'
```

Response:
```json
{
  "success": true,
  "filename": "test.pdf",
  "size_bytes": 13379,
  "pdf_base64": "JVBERi0xLjQK..."
}
```

---

## 🔄 Updating the Server

```bash
ssh azureuser@<VM_IP>
cd /opt/latex-mcp
./scripts/deploy.sh
```

Force full rebuild:
```bash
./scripts/deploy.sh --build
```

---

## 💰 Azure Student Credit Usage

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| B2s_v2 VM (24/7) | ~$35/month | ~3 months on $100 credit |
| B2s_v2 VM (8h/day) | ~$12/month | ~8 months on $100 credit |
| Managed Disk 64GB | ~$4/month | Always charged |
| Static IP | Free (attached) | Free while attached to running VM |
| **Stopped VM** | **~$4/month** | Only disk — stop when not needed! |

**Tip:** Deallocate the VM from Azure Portal when not in use → costs drop to ~$4/month for disk only.

```bash
# Stop VM (save credit)
az vm deallocate --resource-group latex-mcp-rg --name latex-mcp-vm

# Start VM (when needed)
az vm start --resource-group latex-mcp-rg --name latex-mcp-vm
```

---

## 🛡️ Security

- ✅ **API Key auth** on all sensitive endpoints
- ✅ **Rate limiting** via Nginx (30 req/min per IP)
- ✅ **Non-root** container user
- ✅ **Path traversal prevention** on PDF downloads
- ✅ **UFW firewall** (only ports 22, 80, 443 open)
- ✅ **Timing-safe** API key comparison

---

## 📝 License

MIT — free to use and modify.
