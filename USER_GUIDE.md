# PM Batch Validator — User & Admin Guide

A practical guide to using the PM (Preventive Maintenance) Report Validator. It
explains, step by step, how to validate maintenance report PDFs, read the
results, and (for admins) manage the rules, sites, users, and audit trail.

- **Part 1 – For All Users**: signing in, processing reports, reading results.
- **Part 2 – For Admins**: task rules, sites, dashboards, audit log.
- **Part 3 – Reference**: verdicts, troubleshooting, FAQ.

---

# Part 1 — For All Users

## 1.1 What this tool does
You give it preventive‑maintenance **report PDFs**. For each report it:
- reads the checklist items and the inspector's "OK / Not OK" marks,
- pulls the site photos and their date/GPS metadata,
- uses AI plus fixed checks (photo date, GPS distance, and admin‑defined rules)
  to decide whether each item is **confirmed** or **disputed**,
- produces a report with an **Acceptance %** and per‑item explanations.

The heavy work runs **on the server**, so you can lock your screen, close the
tab, or sign out — processing continues and the results are waiting when you
return.

## 1.2 Signing in
1. Open the application URL in **Chrome or Edge** (recommended).
2. **Register** (first time): enter your full name, choose a username and a
   password (minimum 6 characters), and submit.
3. **Login**: enter your username and password.
4. You land on the **Validator** screen. Your previously processed files and
   reports are restored automatically each time you sign in.

> Forgot your password? Contact your administrator — there is no self‑service
> reset.

## 1.3 The Validator screen at a glance
- **Select Folder / ＋ Add Files** — choose the PDFs to process.
- **Run All / Stop All** — start or stop processing for the whole list.
- The **file table**: one row per PDF, showing progress, acceptance %, per‑file
  controls (Run / Stop / Re‑run / Remove), and a link to the report.
- **Summary counters** at the top: Total, Done, Disputed, Average %.
- **LLM status pill** (see §1.3.1) — shows whether the AI service is reachable.

### 1.3.1 The LLM (AI) status indicator
A small status pill shows the health of the AI service that performs the
validation:
- **🟢 LLM Online** — the AI service is reachable; validation can run normally.
- **🔴 LLM Offline** — the AI service can't be reached. The system can still
  upload files and read photo date/GPS, but the **AI verdict step will fail**, so
  runs will end in **Error** until it's back.

The pill is checked automatically. If you see **🔴 LLM Offline**, wait a moment
and refresh; if it stays red, contact your administrator before running — the AI
inference server is likely down or unreachable.

## 1.4 Step‑by‑step: validating reports

### Step 1 — Add your files
- Click **Select Folder** to pick a whole folder of PDFs, or **＋ Add Files** to
  add individual PDFs. Only `.pdf` files are accepted.
- As soon as files are selected, they begin **uploading to the server**. A small
  notification in the **bottom‑right** shows progress, e.g. *"3 of 5 files
  uploaded."*
- **Upload happens once**, at selection time. Running or stopping a file later
  never re‑uploads it.

> While files are uploading, **Run All is disabled** (greyed out). Wait until the
> upload notification finishes — then it enables automatically. This is normal
> and prevents starting a run before the files are on the server.

> If a file fails to upload (e.g. a network glitch), its row shows a **⟳ Retry
> upload** button. Click it to re‑upload just that file. Nothing retries
> silently.

> **Duplicate file names:** if you add a file whose name already exists in your
> list, the tool asks whether to **replace** the existing one or **skip** the new
> one. Choosing *replace* removes the old stored copy and uploads the new file in
> its place; choosing *skip* keeps the original. (File names are the identifier,
> so keep them unique and meaningful.)

### Step 2 — Run
You have two ways to start:
- **Run All** — processes every pending file. All rows start immediately;
  several files are processed **at the same time** and the rest show *"Waiting…"*
  until a slot frees up.
- **▶ Run** (on a single row) — processes just that one file.

Each row's progress bar advances through stages (Submitting → Extracting →
Validating → Complete). Each bar reflects **only its own file**.

### Step 3 — Stop (optional)
- **■ Stop** (on a row) — stops just that one file. Other files keep running.
- **Stop All** — stops everything currently running.
- A stopped file can be **re‑run** at any time; it reuses the already‑uploaded
  file (no re‑upload).

These four controls — **Run, Stop, Run All, Stop All** — work independently and
in any order. For example: Run All → Stop one file → Run it again → Stop All all
behave consistently.

### Step 4 — Leave if you want
Because processing runs on the always‑on server, you may **lock the screen,
close the tab, or sign out**. When you come back and sign in, the table shows the
live or finished status. A blue banner ("☁ Server is processing…") appears while
work is in progress.

### Step 5 — View the report
When a file reaches **Done**, click **View Report →** on its row.

### Step 6 — Save the report (important)
Inside the open report there is a **💾 Save Report** button. Processing a file
shows the result on your screen, but the result is **not stored** until you click
**Save Report**.

- **Only saved reports appear in the Dashboard** (yours) **and in the Admin
  Dashboard** (for admins). If you don't save, an admin cannot see the report.
- Save the reports you want to keep/share; you'll get a *"✓ Report saved"*
  confirmation.

## 1.5 Reading a report
The report opens in a window with:
- **Header**: Task ID, Site ID, Task Category/Subcategory, Report Date, FME.
- **Overall verdict**: *Validated* (all items confirmed) or *Disputed* (one or
  more items not confirmed), plus the **Acceptance %**.
- **Per‑item rows**, each showing:
  - **Item Description** — the checklist task text.
  - **Photo Checks** — thumbnails plus, for each photo, two pills. **Click any
    thumbnail to open the photo full‑size** in a viewer (lightbox); you can step
    through the item's photos and close it to return to the report.
    - **Date** — `✓ <date>` if the photo's capture date is within tolerance of
      the report date; `✗ Date missing` if the photo has no readable date; or
      `✗ <date>` if it's outside tolerance.
    - **GPS** — `✓ On‑site (Nm)` if the photo was taken within the allowed radius
      of the registered site; `✗ Off‑site (Nm)` if too far; `✗ GPS missing` if
      the photo has no location.
  - **MS Report** — what the inspector marked (OK / Not OK).
  - **AI Explanation** — 1–2 sentences (in Persian or English to match the
    report) explaining the verdict.
  - **AI Verdict** — see §3.1 for the full meaning of each label/badge.

## 1.6 Your Dashboard
Click the **Dashboard** tab to see all reports **you** have produced.

> **Only reports you saved** (with **💾 Save Report**, §Step 6) appear here. A
> processed‑but‑unsaved file will not show up in the Dashboard.

- **Filter** by Task ID, Site ID, and min/max Acceptance %.
- **Sort** by clicking column headers (e.g. Acceptance Rate).
- Summary KPIs update to match your current filter.
- Click any row to open its full report.

## 1.7 Managing the file list
- **🗑 (Remove)** on a row deletes that file and its stored copy.
- **Clear Folder** removes all files (disabled while a run is active).
- **＋ Add Files** can be used at any time to queue more PDFs.

---

# Part 2 — For Admins

Admins see extra tabs: **Dashboard (all users)**, **Audit**, **Task Rules**, and
**Sites**. Admin sign‑in is the same as any user; the initial admin account is
created from server configuration (`ADMIN_USERNAME` / `ADMIN_PASSWORD`).

> **Security:** change the default admin password before going live.

## 2.1 Admin Dashboard (all users)
The Dashboard for an admin shows reports from **every user**, with an **Owner**
column. You can filter by Owner, Task ID, Site ID, Category/Subcategory, date,
FME, and Acceptance %, and sort by any column. Use this to review output across
the whole team.

- **Saved reports only.** The Admin Dashboard shows only reports that their owner
  **saved** with **💾 Save Report**. If a user processed a file but didn't save
  it, it won't appear here — ask them to open it and click Save Report.
- **Open the report:** click a row to view the full report, including photos.
  Click any **thumbnail** to see the image **full‑size**.
- **Download the original PDF:** click the **file name** in a row to download the
  **original PDF** that the owner uploaded (opens in a new tab). This is the
  source report, exactly as submitted.

## 2.2 Task Rules — teaching the AI what "pass" means
Task Rules let you add extra, item‑specific validation criteria that are injected
into the AI's check for that item.

### How a rule is matched to an item
A rule is applied only when **all three** match the report:
1. **Task Category** = the report's parsed Task Category (exact text).
2. **Task Subcategory** = the report's parsed Task Subcategory (exact text).
3. **Task #** = the checklist **row number** of the item.

> Tip: if unsure of the exact category/subcategory text or row numbers, open one
> processed report and copy the values from its header and rows. They must match
> character‑for‑character.

### Adding a rule
In the **Task Rules** tab, **Add / Update Rule** form:
- **Task Category**, **Task Subcategory**, **Task #** — the matching keys above.
- **Expected condition** — a sentence describing what a passing photo/result
  looks like.
- **Checkpoints** (one per line) — specific things that should be visibly true.
- **Fail if** (one per line) — conditions that should cause the item to fail.

Click save; the rule appears in the table and takes effect on the **next run** of
a matching report. Edit by re‑saving the same keys; delete with the row's delete
action.

**Example — a hinge‑greasing item (row 15):**
| Field | Value |
|---|---|
| Task Category | `Site and Tower Inspection` |
| Task Subcategory | `NW Fence and Shelter Inspection` |
| Task # | `15` |
| Expected | `Photos must clearly show fresh grease applied to the gate/door hinges. Pipes are NOT the subject.` |
| Checkpoints | `Gate/door hinge clearly visible` / `Fresh grease visible on the hinge pivot` |
| Fail if | `No hinge visible` / `No grease applied` / `Photo shows pipes/cables instead of hinges` |

### Bulk import (CSV)
The Task Rules tab supports CSV import. Columns:
`taskCategory, taskSubcategory, taskNumber, expected, checkpoints, fail_if`.
Separate multiple checkpoints / fail_if items with a pipe `|`. A template is
downloadable from the tab.

### Important: what rules can and cannot do
- Rules **guide** the AI's judgement of an item — they make it pay attention to
  your criteria.
- Rules **do not force** a verdict. If the photos clearly satisfy the task, the
  AI may still confirm it; if they clearly don't, it will dispute it. Write rules
  about the item's **real subject**.
- The only **hard, automatic** failures are the **photo date** and **GPS
  distance** checks (configured server‑side) — those are computed by code, not by
  the AI.

## 2.3 Sites — coordinates for GPS validation
The **Sites** tab holds the official coordinates used for the GPS check.
- Add a site with **Site ID**, **Latitude**, **Longitude** (lat/lon must be
  numeric).
- Delete sites you no longer need.
- During validation, each photo's GPS is compared to its site's coordinates; a
  photo farther than the allowed radius is flagged **Off‑site**.
- Bulk import via CSV is supported (columns `siteId, lat, lon`).

> If a site has no entry here, photos for it will show **GPS missing / Off‑site**
> because there's nothing to compare against. Keep this list current.

## 2.4 Audit Log
The **Audit** tab records key events: logins, run requested/started/finished,
single and bulk stops, cancellations, rule and site changes, and more — each with
the user and timestamp. Filter by user, event type, or task to investigate
activity.

## 2.5 Admin responsibilities checklist
- Keep **Sites** up to date so GPS checks are meaningful.
- Maintain **Task Rules** for items that need specific criteria.
- Review the **Admin Dashboard** for low‑acceptance or disputed reports.
- Use the **Audit Log** to track who did what.
- Manage the admin password and any user issues.

---

# Part 3 — Reference

## 3.1 Understanding verdicts and badges
For each item the report shows one of:
- **OK** — the item is **confirmed** (counts toward Acceptance %).
- **Not OK** — the item is **disputed** (does not count as confirmed). It then
  carries one of two clarifying badges:
  - **Technically Compliant** — the work itself looks fine; the item is flagged
    **only** because the photo evidence couldn't be verified (date and/or GPS).
  - **Technically Non‑Compliant** — flagged for a genuine content reason (e.g.
    the photo doesn't show the required work, is irrelevant, or shows a defect).
- **—** — no evidence available.

Common reason tags you may see: *Date mismatch*, *GPS mismatch*, *GPS missing*,
*Irrelevant image*, *Marked OK — defect visible*, *Marked Not OK — looks fine*,
*Poor photo quality*.

**Acceptance %** = confirmed items ÷ total items, as a percentage. Higher is
better; it is colour‑coded (green ≥ 80, amber 50–79, red < 50).

## 3.2 The photo Date and GPS checks
- **Date**: each photo's capture date must be within the configured tolerance
  (default ±3 days) of the report date. Missing/unreadable date → `Date missing`.
- **GPS**: each photo's location must be within the configured radius (default
  300 m) of the registered site. No location → `GPS missing`.
- These are **automatic** and independent of the AI and of Task Rules.

## 3.3 Persian (RTL) reports
Persian reports are fully supported. Item text is normalized automatically so it
displays correctly. (Some source PDFs embed text in unusual ways; the tool
cleans this up, and even if a description looks slightly off, the verdict and
scoring are unaffected.)

## 3.4 Troubleshooting

| Symptom | What to do |
|---|---|
| **Run All is greyed out** | Files are still uploading — wait for the bottom‑right "x of N uploaded" to finish. |
| **A row shows "⟳ Retry upload"** | That file's upload failed; click it to re‑upload just that file. |
| **Files show "Waiting…" for a while** | Normal — only a few files process at once; they start as slots free up. |
| **I closed the tab — did I lose my run?** | No. Processing continues on the server; sign back in to see progress/results. |
| **A report failed (Error)** | Re‑run that file. If it keeps failing, the PDF may be corrupt or the AI service may be temporarily unavailable — tell your admin. |
| **Status shows 🔴 LLM Offline** | The AI service is unreachable; runs will Error at the AI step. Wait and refresh; if it stays red, contact your admin (the inference server is likely down). |
| **My report isn't in the Dashboard / admin can't see it** | You must open the report and click **💾 Save Report**. Only saved reports appear in the Dashboard and Admin Dashboard. |
| **Adding a file did nothing / asked to replace** | A file with that name already exists; choose **replace** to overwrite or **skip** to keep the original. |
| **A task rule "isn't working"** | Check the rule's Category/Subcategory/Task # match the report exactly, and remember rules guide (not force) the AI. Re‑run the file after changing a rule. |
| **Photos don't appear in a report** | The photos may not have uploaded to storage for that task; re‑run the file. |
| **Login fails** | Verify username/password; contact your admin if needed. |

## 3.5 Frequently asked questions

**Q: Do I need to keep my computer on while it processes?**
No. Work runs on the server. You can lock, close, or sign out.

**Q: Will running a file upload it again?**
No. Upload happens once when you select files. Run/Stop/Re‑run reuse it.

**Q: Can I stop one file without affecting the others?**
Yes. Each file is independent — Stop on a row affects only that file.

**Q: What's the difference between "Technically Compliant" and "Non‑Compliant"?**
"Compliant" means the only problem is unverifiable photo date/GPS; the work looks
fine. "Non‑Compliant" means there's a real content problem with the evidence.

**Q: Why is acceptance below 100% even though the inspector marked everything OK?**
Because the tool independently checks the **photos** (date, GPS, relevance, and
admin rules). If the evidence doesn't support an item, it's disputed regardless
of the inspector's mark.

**Q: Can admins see my reports?**
Admins have an all‑users dashboard for oversight, but they see a report **only
after you save it** with **💾 Save Report**. Unsaved results stay on your screen
only.

**Q: What does the LLM Online / Offline pill mean?**
It's the health of the AI service. **🟢 Online** = validation can run. **🔴
Offline** = the AI is unreachable and runs will Error at the AI step; wait or tell
your admin.

**Q: How do I see a photo full‑size?**
Open the report and **click the thumbnail** — it opens in a full‑size viewer.

**Q: (Admins) How do I get the original submitted PDF?**
In the Admin Dashboard, **click the file name** in the report's row to download
the original PDF the owner uploaded.

---

## Quick reference card

**User flow:** Sign in → Select Folder / Add Files → wait for upload → **Run All**
→ watch progress → **View Report** → **💾 Save Report** → review on **Dashboard**.

**Controls:** ▶ Run (one) · ■ Stop (one) · Run All · Stop All — all independent.

**Admin extras:** Task Rules (item criteria) · Sites (GPS coordinates) · Audit
(activity) · Dashboard (all users) — **click a file name to download the original
PDF**.

**Remember:**
- Upload happens once at selection (duplicate names prompt replace/skip).
- A result is only stored — and visible to admins — after you click **💾 Save
  Report**.
- Click a **thumbnail** to view a photo full‑size.
- Watch the **🟢 LLM Online / 🔴 LLM Offline** pill — runs need the AI online.
- Processing is server‑side (you can leave any time) · Date/GPS checks are
  automatic · Task Rules guide the AI, they don't force a verdict.
