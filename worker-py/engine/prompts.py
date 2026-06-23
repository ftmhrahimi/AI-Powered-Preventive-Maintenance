"""LLM prompts ported VERBATIM from the frontend SPA so the Python engine
behaves identically. Do not reword these without re-validating parity.

Sources in frontend/index.html:
  - callLLMExtract           (item clean/dedup, EN + FA)
  - cleanConsecutiveTasks    (neighbour bleed-fix, FA)
  - detectCheckboxFromStrip  (OK / NOT_OK from a row image)
  - buildValidationPrompt    (per-item verdict)
"""

# ── Item clean / dedup (LLM pass #1) ─────────────────────────────────────────
EXTRACT_EN = (
    'Extract numbered maintenance tasks from this English text. Each item starts '
    'with a number like "1.", "2.", etc.\n'
    'The same description may appear 2-5 times repeated — pick it ONCE only.\n'
    'Return ONLY a JSON array, no markdown:\n'
    '[{"num":1,"desc":"full task description","result":"NOT_OK"}]\n'
    'Rules:\n'
    '- num = the leading integer\n'
    '- desc = the complete clean description for that number, NO repetition inside desc\n'
    '- result is always NOT_OK\n'
    '- One entry per number, never duplicate the same number\n'
    "- If the same sentence appears multiple times inside one item's text, include it only once\n"
    '- Ignore lines without a number prefix\n'
    '- Ignore lines containing only "battery wo falt darad" or "Not OK" or "OK"\n'
    'RAW TEXT:\n{chunk}'
)

EXTRACT_FA = (
    'The following text is raw Persian text extracted from a PDF. Due to PDF '
    'encoding issues, Persian words are broken into separate letters with spaces '
    'between them, and word order may be reversed.\n'
    'CRITICAL: Do NOT translate. Keep original Persian words.\n'
    'STEP 1 — For each Persian word: remove spaces between letters and join them '
    'into one word. Example: " ﺍﻃﻤیﻨﺎﻥ" becomes "اطمینان".\n'
    'STEP 2 — If the sentence reads backwards, reverse the word order.\n'
    'STEP 3 — Extract each unique numbered maintenance task.\n'
    'STEP 4 — Remove duplicate sentences.\n'
    'Return ONLY a JSON array — no markdown, no preamble.\n\n'
    'Format: [{"num":1,"desc":"fixed persian description","result":"NOT_OK"}]\n\n'
    'Rules:\n'
    '- Ignore header lines (Site ID, Contractor, Region, Task ID, etc.)\n'
    '- Do NOT mix text from different task numbers.\n'
    '- One entry per task number only.\n\n'
    'RAW TEXT:\n{chunk}'
)


def extract_prompt(chunk: str, is_english: bool) -> str:
    return (EXTRACT_EN if is_english else EXTRACT_FA).format(chunk=chunk)


# ── Neighbour bleed-fix (LLM pass #2, FA) ────────────────────────────────────
def bleed_fix_prompt(curr_num, curr_desc, nb_num, nb_desc) -> str:
    return (
        'You are cleaning text extracted from a Persian/English PDF maintenance report.\n'
        f'Task {curr_num} below incorrectly contains text that belongs to task {nb_num}.\n'
        f'Remove ONLY the part from task {nb_num} that has bled into task {curr_num}.\n'
        f'Keep task {curr_num} own description fully intact.\n\n'
        f'Task {curr_num} (dirty — contains bleed-in from task {nb_num}):\n{curr_desc}\n\n'
        f'Task {nb_num} reference text (remove this from task {curr_num}):\n{nb_desc}\n\n'
        'Return ONLY valid JSON, no markdown:\n'
        f'{{"num":{curr_num},"desc":"cleaned text of task {curr_num} only"}}'
    )


# ── Checkbox detection (vision) ──────────────────────────────────────────────
CHECKBOX = (
    'This image shows a single checkbox row from a maintenance report. \n'
    'It contains two checkboxes: one for "OK" and one for "Not OK". \n'
    'Look carefully at which checkbox has a checkmark/tick inside it.\n'
    'Return ONLY one of these two values, nothing else:\n'
    'OK\n'
    'NOT_OK'
)


# ── Per-item validation (vision) ─────────────────────────────────────────────
def validation_prompt(item, photo_count, report_date, site_lat, site_lon,
                      meta_summary, rule, header) -> str:
    """Verbatim port of buildValidationPrompt."""
    if rule:
        rule_text = (
            f"EXPECTED CONDITION: {rule.get('expected') or '-'}\n"
            "CHECKPOINTS:\n" + "\n".join('- ' + c for c in (rule.get('checkpoints') or [])) +
            "\nFAIL CONDITIONS:\n" + "\n".join('- ' + f for f in (rule.get('fail_if') or []))
        )
    else:
        rule_text = 'No additional rules provided.'
    gps = f"{site_lat}, {site_lon}" if site_lat else 'not registered'
    return f"""You are an expert AI validator for Irancell PM (Preventive Maintenance) reports.
TASK: Validate ONE checklist item using ONLY its dedicated site photos.

REPORT:
  Task ID:     {header.get('taskId') or '?'}
  Site ID:     {header.get('siteId') or '?'}
  Report Date: {report_date}
  Site GPS:    {gps}

ITEM TO VALIDATE:
  Row: {item['num']} | Description: {item['desc']} | Reported: {item.get('result') or 'NO_RESULT'} | Photos: {photo_count}

ADDITIONAL VALIDATION RULES:
{rule_text}

CRITICAL DATA for latitude and longitude (TRUST ONLY THIS):
  {meta_summary}

IMPORTANT: Date and GPS validation are already handled by the system.
CRITICAL:DO NOT analyze dates visible inside images, timestamps, watermarks, GPS text, or coordinates.
Only analyze: whether the image is relevant to the maintenance condition, whether the maintenance condition matches the reported status, whether the photo quality is sufficient.

Determine:
1. VERDICT: "CONFIRMED" | "DISPUTED" | "NO_EVIDENCE"
2. CAUSES (only applicable): "IRRELEVANT_IMAGE" | "MARKED_OK_BUT_DEFECT" | "MARKED_NOTOK_BUT_FINE" | "PHOTO_QUALITY"
3. EXPLANATION: 1-2 sentences in persian when task written in persian and english when task written in english.

Return ONLY valid JSON (no markdown):
{{"row":{item['num']},"verdict":"CONFIRMED","causes":[],"explanation":"…"}}"""
