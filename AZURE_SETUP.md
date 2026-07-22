# Azure Setup Guide — Resume AI Builder

## Overview

You need two Azure resources:
1. **Azure CosmosDB for PostgreSQL** — stores your knowledge graph (projects, skills, roles) and session state
2. **Azure Blob Storage** — stores the locked master template and generated PDFs/LaTeX

Total cost: ~$15–20/month on smallest tiers (B1ms DB + LRS Blob).

---

## Part 1: Azure CosmosDB for PostgreSQL

### Step 1.1 — Create the Database

1. Go to [portal.azure.com](https://portal.azure.com) → **Create a resource**
2. Search for **"Azure CosmosDB"** → select **"Azure CosmosDB for PostgreSQL"**
3. Click **Create**

### Step 1.2 — Basics Tab

| Field | Value |
|---|---|
| **Subscription** | Your subscription |
| **Resource group** | Create new: `resume-builder-rg` |
| **Cluster name** | `resume-pg` (must be globally unique — append numbers if taken) |
| **Location** | Pick closest to you (e.g., `East US`, `West Europe`, `Central India`) |
| **PostgreSQL version** | 16 |
| **Scale** | Select **"Single node"** |
| **Compute + storage** | Click **Configure** |

#### Compute Configuration

1. Under **Node**, select:
   - **Burstable (B1ms)** — 1 vCore, 2 GiB RAM (~$17/month)
   - **Storage**: 32 GiB (minimum, more than enough)
2. Or select **Free tier** if available in your region (1 vCore, 2 GiB, 32 GiB storage — $0 for first 12 months)
3. Click **OK**

### Step 1.3 — Authentication

| Field | Value |
|---|---|
| **Admin username** | `resumeadmin` (or anything you prefer) |
| **Password** | Create a strong password (save it!) |
| **Confirm password** | Same as above |

> ⚠️ **Save this password immediately.** You'll need it for the connection string.

### Step 1.4 — Networking

1. Select **"Public access"**
2. Under **Firewall rules**, click **"+ Add 0.0.0.0 - 255.255.255.255"** IF you want access from anywhere (OK for dev).
   - Better for production: Add only your IP. Note that your home IP changes periodically.
   - Or check **"Allow public access from any Azure service"** + add your specific IP.
3. Check **"Allow public access from any Azure service"** — this lets your App Service connect if you deploy there later.

### Step 1.5 — Review + Create

1. Click **Review + create**
2. Verify settings → click **Create**
3. Wait ~5 minutes for deployment

### Step 1.6 — Get Your Connection String

1. After deployment, go to **"Go to resource"**
2. In the left sidebar, under **Settings**, click **"Connection strings"**
3. Copy the **"psql"** connection string. It looks like:

```
psql "host=resume-pg.postgres.cosmos.azure.com port=5432 dbname=citus user=resumeadmin password=YOUR_PASSWORD sslmode=require"
```

4. Convert it to asyncpg format:

```
# From:
psql "host=resume-pg.postgres.cosmos.azure.com port=5432 dbname=citus user=resumeadmin password=MyP@ssw0rd sslmode=require"

# To:
postgresql://resumeadmin:MyP%40ssw0rd@resume-pg.postgres.cosmos.azure.com:5432/citus?sslmode=require
```

> 📌 **Critical:** The `@` in your password MUST be URL-encoded as `%40`.
> Other special chars: `:` → `%3A`, `/` → `%2F`, `%` → `%25`, `#` → `%23`

5. Paste this into your `.env` file as `AZURE_COSMOSDB_PG_URL`.

### Step 1.7 — Create the Application Database (Optional)

By default, the server connects to the `citus` database. You can create a dedicated one:

1. In the Azure Portal, go to your CosmosDB resource
2. Click **"Databases"** in the left sidebar (under Settings)
3. Click **"+ Add database"** → name it `resumedb`
4. Update your connection string to use `resumedb` instead of `citus`.

---

## Part 2: Azure Blob Storage

### Step 2.1 — Create Storage Account

1. Go to [portal.azure.com](https://portal.azure.com) → **Create a resource**
2. Search for **"Storage account"** → select it → **Create**

### Step 2.2 — Basics Tab

| Field | Value |
|---|---|
| **Subscription** | Same as above |
| **Resource group** | `resume-builder-rg` (same group) |
| **Storage account name** | `resumebuilderstorage` (lowercase, no hyphens, must be globally unique) |
| **Region** | Same region as your PostgreSQL |
| **Performance** | **Standard** |
| **Redundancy** | **Locally-redundant storage (LRS)** — cheapest, fine for personal use |

### Step 2.3 — Advanced Tab

- **Enable hierarchical namespace**: Leave **OFF** (we don't need Data Lake)
- **Allow enabling anonymous access**: Leave **OFF**
- Everything else: defaults are fine

### Step 2.4 — Review + Create

1. Click **Review + create**
2. Click **Create**
3. Wait ~1 minute

### Step 2.5 — Get Connection String

1. Go to your storage account → **Security + networking** → **Access keys**
2. Click **"Show keys"**
3. Copy **"Connection string"** under **key1**. It looks like:

```
DefaultEndpointsProtocol=https;AccountName=resumebuilderstorage;AccountKey=aGVsbG8gd29ybGQgdGhpcyBpcyBhIGZha2Uga2V5IGZvciBleGFtcGxl...==;EndpointSuffix=core.windows.net
```

4. Paste into your `.env` as `AZURE_STORAGE_CONNECTION_STRING`.

### Step 2.6 — Create Container

1. Go to your storage account → **Data storage** → **Containers**
2. Click **"+ Container"**
3. Name: `resume-archive`
4. Public access level: **Private (no anonymous access)**
5. Click **Create**

### Step 2.7 — Upload Master Template

1. In the `resume-archive` container, click **"Upload"**
2. Upload `template/master_resume.tex` from your project
3. Create folder `templates/` first (optional — you can also upload directly and rename):
   - Click **"+ Add directory"** → name it `templates`
   - Navigate into `templates/` → click **Upload**
   - Select `template/master_resume.tex` → upload
4. The template is now at `templates/master_resume.tex` in your container.

You can also use the included upload script:
```bash
cd server
AZURE_STORAGE_CONNECTION_STRING="..." AZURE_STORAGE_CONTAINER="resume-archive" \
  TEMPLATE_BLOB_PATH="templates/master_resume.tex" \
  python tests/upload_template.py
```

---

## Part 3: Files at a Glance

```
Storage Account: resumebuilderstorage
  Container: resume-archive
    ├── templates/
    │   └── master_resume.tex          ← Uploaded manually (Phase 1)
    │
    └── resumes/
        ├── tata-consultancy-services/
        │   └── ai-ml-prompt-engineer/
        │       ├── tcs_aiml_abc123def.../
        │       │   ├── resume.pdf
        │       │   ├── resume.tex
        │       │   └── metadata.json
        │       └── tcs_aiml_xyz789.../
        │           └── ...
        └── google/
            └── software-engineer/
                └── google_swe_123.../
                    └── ...
```

The versioning by **company** → **role** → **session_key** means:
- You can browse all resumes generated for a specific company
- You can browse all versions for a specific role at that company
- Each session_key is unique per JD+sections combination (no duplicates unless same input)

---

## Part 4: Verify Everything

### 4.1 — Test PostgreSQL Connection

```bash
# Install psql if needed: brew install libpq (macOS) or apt install postgresql-client

psql "host=resume-pg.postgres.cosmos.azure.com port=5432 dbname=citus user=resumeadmin password=YOUR_PASSWORD sslmode=require"
```

Once connected:
```sql
SELECT version();  -- Should show PostgreSQL 16.x
\dt                -- Should be empty (schema created on first server run)
\q
```

### 4.2 — Run Migrations and Seed

```bash
cd server

# With your .env properly filled in:
AZURE_COSMOSDB_PG_URL="postgresql://resumeadmin:pass@resume-pg.postgres.cosmos.azure.com:5432/resumedb?sslmode=require" \
  python -m server.db.seed
```

### 4.3 — Start the Server

```bash
docker compose up
# or locally:
cd server && uvicorn server.main:app --reload
```

Visit http://localhost:8000/health → should return `{"status": "ok"}`

Visit http://localhost:8000/docs → FastAPI Swagger UI with all endpoints

### 4.4 — Verify Admin Endpoints

```bash
# List skills
curl http://localhost:8000/api/admin/skills

# List projects
curl http://localhost:8000/api/admin/projects

# List roles
curl http://localhost:8000/api/admin/roles
```

---

## Troubleshooting

### "SSL connection has been closed unexpectedly"
Azure CosmosDB requires SSL. Make sure your URL has `?sslmode=require` at the end.

### "password authentication failed"
Your password probably contains special characters that need URL encoding. Encode them:
- `@` → `%40`, `:` → `%3A`, `/` → `%2F`, `%` → `%25`, `#` → `%23`

### "FATAL: no pg_hba.conf entry for host"
Your IP is not in the firewall rules.
Go to Azure Portal → CosmosDB → Networking → Add your IP address.

### "Container not found" (Blob Storage)
The container `resume-archive` must exist BEFORE the server starts.
Create it manually in the Azure Portal (Step 2.6).

### "Blob not found: templates/master_resume.tex"
Upload the template manually (Step 2.7) or run `python server/tests/upload_template.py`.

### Server starts but can't connect
Check: is `AZURE_COSMOSDB_PG_URL` set? The server reads BOTH `AZURE_COSMOSDB_PG_URL` and `DATABASE_URL`, using the Azure one if present.
