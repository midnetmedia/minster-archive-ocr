# Free full-archive OCR with GitHub Actions

This runs Tesseract OCR over **all 6,499 newspaper PDFs** on GitHub's free servers
(no need to leave your computer on), builds the Pagefind search index, and uploads
it to your S3 bucket. Cost: **$0** for compute, ~$0.03/month to store the index.

You do this **once**. After that, the archive is fully searchable.

---

## What gets uploaded to GitHub

Only these (small) files — **never** the PDFs and **never** the search index:

```
.github/workflows/ocr.yml   ← the automation
ocr_pipeline.py             ← the OCR engine
build_index.mjs             ← builds the Pagefind index
full_keys.json              ← the list of all 6,499 PDFs
package.json / package-lock.json
.gitignore
```

The `.gitignore` already blocks the big stuff (PDFs, `node_modules/`, `*.jsonl`, the index).

---

## Step 1 — Create a public GitHub repo

1. Go to <https://github.com/new>.
2. Name it e.g. `minster-archive-ocr`.
3. Set it to **Public** (free unlimited build minutes; the newspapers are public domain).
4. **Don't** add a README/license (we're uploading existing files).
5. Click **Create repository**.

### Upload the files (easiest, no command line)
1. On the new repo page, click **uploading an existing file**.
2. Drag in the files listed above from `~/Desktop/minster-search/`.
   - Include the **`.github/workflows/ocr.yml`** path — GitHub's web uploader keeps
     folders if you drag the `.github` folder itself.
3. **Commit changes.**

> Prefer the command line? In `~/Desktop/minster-search/` run:
> ```
> git init && git add . && git commit -m "OCR pipeline"
> git branch -M main
> git remote add origin https://github.com/YOURNAME/minster-archive-ocr.git
> git push -u origin main
> ```

---

## Step 2 — Make an AWS key that can only write the index

This key lets GitHub upload the finished index to S3, and **nothing else**.

1. AWS Console → **IAM** → **Users** → **Create user** (e.g. `pagefind-deployer`).
   - **No** console access needed.
2. **Next** → **Attach policies directly** → **Create policy** → **JSON** tab.
3. Paste the contents of [`aws/pagefind-deployer-policy.json`](aws/pagefind-deployer-policy.json)
   (it's scoped to `pagefind/*` only — it can't touch your PDFs). Name it
   `pagefind-deployer-policy`, create it, then attach it to the user.
4. Open the user → **Security credentials** → **Create access key** →
   **Application running outside AWS**.
5. Copy the **Access key ID** and **Secret access key** (you'll see the secret once).

---

## Step 3 — Add the key to GitHub as Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret.**
Add two:

| Name | Value |
|------|-------|
| `AWS_ACCESS_KEY_ID` | the Access key ID from Step 2 |
| `AWS_SECRET_ACCESS_KEY` | the Secret access key from Step 2 |

> If your bucket isn't in `us-east-1`, tell me and I'll change the region in the workflow.

---

## Step 4 — Run it

1. Repo → **Actions** tab → **"OCR archive → Pagefind index"** → **Run workflow**.
2. Watch the 20 shards run in parallel (~30–60 min for a full pass).
3. When all shards finish, the **build-index** job builds the index and pushes it to S3.

### If a shard says "stopped-early"
That's the 5-hour safety stop — totally normal on a first pass if a shard is large.
Just click **Run workflow** again. Finished shards skip instantly (they exit in seconds),
and the slow ones continue exactly where they left off. Repeat until every shard logs
`[done] … 0 remaining`. Usually 1–2 passes total.

---

## Watching progress

Every run shows a **progress panel** on its summary page (Actions → click the run).
You'll see a bar like this, updated each pass:

> ## 📰 Archive OCR progress
> `████████░░░░░░░░░░░░`  **41.3%**
>
> | Metric | Count |
> |---|---|
> | Documents OCR'd | **2,684** / 6,499 |
> | Documents remaining | 3,815 |
> | Pages indexed | 38,902 |
>
> ⏳ Re-run the workflow to continue the remaining documents.

Each shard also reports its own `done/assigned` count, and the live logs print
`[shard N] X/Y docs done … remaining` as it goes.

### Optional: status badge in a README
Add this to a `README.md` in the repo to show the last run's pass/fail at a glance
(replace `YOURNAME/minster-archive-ocr`):

```markdown
![OCR](https://github.com/YOURNAME/minster-archive-ocr/actions/workflows/ocr.yml/badge.svg)
```

---

## Step 5 — Confirm it's live

Open in a browser:
```
https://s3.amazonaws.com/archives.minsterhistoricalsociety.com/pagefind/pagefind.js
```
If it loads, the full index is live and your Duda search now covers the entire archive —
no widget changes needed (it already points at this `pagefind/` folder).

---

## How it stays cheap & safe
- **Public repo** → unlimited free Actions minutes, 20 concurrent jobs.
- **`--resume` + cache** → never re-OCRs a page that's already done; safe to re-run.
- **Scoped IAM key** → GitHub can only write the `pagefind/` index folder, not your PDFs.
- **Only real cost** → one-time S3 egress to download the PDFs to the runners (a few GB ≈ well under $1).
