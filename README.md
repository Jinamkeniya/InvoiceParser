# Invoice Extractor

A Flask web application that extracts structured data from photos of handwritten/printed garment invoices using a local vision-language model (VLM) and exports the results to CSV and Excel.

The app is built for invoices that combine printed templates with handwritten fields (invoice number, date, quantities, rates, amounts, GST totals, etc.). It runs a domain-specific extraction prompt, then applies seven arithmetic and format validation rules and, where needed, re-prompts the model with targeted corrections.

## Features

- Drag-and-drop upload of one or many invoice images (JPG / PNG)
- Local VLM extraction via [Ollama](https://ollama.com/) (default model: `qwen2.5vl:3b`)
- Two-pass pipeline: initial extraction -> validation -> auto-fix or targeted re-extraction
- Seven business-rule validators:
  - Customer GSTIN format (15 alphanumeric chars, starting with `27`)
  - `CGST == SGST`
  - `Gross Total - Discount == Total After Discount`
  - `SGST` and `CGST` each equal 2.5% or 6% of Total After Discount
  - `Net Total == Total After Discount + SGST + CGST`
  - Date format sanity (handles `|` separators confused with digit `1`)
  - Per line item: `Qty * Rate == Amount`
- Results page with per-invoice fields, line items, and any unresolved validation warnings
- Downloads: `invoices_summary.csv`, `invoices_items.csv`, and a combined `invoices_output.xlsx`
- Batch mode: process every image in the local `images/` folder with one click

## Project structure

```
Invoice/
├── app.py                    # Flask routes (upload, process, download)
├── requirements.txt
├── extraction/
│   ├── prompts.py            # EXTRACTION_PROMPT and MODEL_NAME
│   ├── vlm_extractor.py      # Ollama call, normalization, retry loop
│   └── validator.py          # 7 business rules + auto_fix + correction prompt
├── export/
│   └── csv_export.py         # CSV + Excel writer
├── templates/
│   ├── index.html            # Upload UI
│   └── results.html          # Results UI
├── static/
│   └── style.css
├── images/                   # (optional) drop invoices here for batch mode
├── uploads/                  # per-job uploaded files (git-ignored)
└── results/                  # per-job CSV/Excel output (git-ignored)
```

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/download) running locally
- The vision model pulled in Ollama:

```bash
ollama pull qwen2.5vl:3b
```

To use a different model, edit `MODEL_NAME` in `extraction/prompts.py`.

## Setup

```bash
git clone <this-repo>
cd Invoice

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

Make sure the Ollama service is running (`ollama serve` or the desktop app), and that `qwen2.5vl:3b` (or your chosen model) is available.

## Running the app

```bash
source venv/bin/activate
python app.py
```

Then open <http://localhost:5000>.

From the UI you can either:

1. Upload one or more invoice images via drag-and-drop, then click **Extract Invoice Data**, or
2. Click **Process All Images in /images Directory** to batch-process every image in the local `images/` folder (useful for testing).

CPU inference typically takes 20–60 seconds per image.

## Output

Every run creates a new job folder under `results/<job_id>/` containing:

- `invoices_summary.csv` — one row per invoice (totals, customer, GSTIN, etc.)
- `invoices_items.csv` — one row per line item (HSN, description, size, qty, rate, amount)
- `invoices_output.xlsx` — both sheets in a single Excel workbook (when `openpyxl` is installed)

The results page also surfaces any validation rules that could not be automatically reconciled, so you can eyeball the original image and fix up the CSV if needed.

## How extraction works

1. `extract_invoice(image_path)` sends the image and `EXTRACTION_PROMPT` to the Ollama VLM in JSON mode.
2. The raw response is parsed and normalized into a stable schema (numbers coerced to floats, empty strings to `None`, etc.).
3. `validate(data)` runs the seven business rules and returns any failures.
4. `auto_fix` resolves what it can mechanically (for example, snapping unequal CGST/SGST values to the nearest valid 2.5% / 6% tax).
5. For anything left over, `build_correction_prompt` appends the failing checks to the extraction prompt and re-runs the VLM (up to `validation_retries` times).
6. Any still-unresolved failures are returned on the result as `_discrepancies` and displayed as warnings in the UI.

## Notes & limitations

- The extraction prompt is tuned to a specific family of garment invoices (two-header layout, handwritten totals in a fixed place, GSTIN starting with `27`, tax rates of 2.5% or 6%). Expect to edit `extraction/prompts.py` for other invoice styles.
- `uploads/`, `results/`, and `images/` are git-ignored; only the code and templates are tracked.
- The Flask dev server (`app.run(debug=True)`) is fine for local use but should not be exposed directly in production.
