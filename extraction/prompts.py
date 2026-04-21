EXTRACTION_PROMPT = """You are an expert invoice data extractor. Extract ALL information from this invoice image and return it as a JSON object.

The invoice contains both PRINTED text (black on pink/white paper) and HANDWRITTEN text (blue ink). Read the handwritten text very carefully.

IMPORTANT LAYOUT NOTES:
- There may be TWO headers: an outer company header (e.g. "DURLABHSONS EXPORTS PVT. LTD.") and an inner vendor header (e.g. "Sixth Sense"). The VENDOR is the inner/main brand name.
- The invoice number is next to "INVOICE No." on the vendor's section (NOT from any outer header).
- The date is HANDWRITTEN next to "Date" on the same row as the invoice number. CRITICAL: the day, month, and year are separated by VERTICAL LINES (|), NOT slashes or dashes. The vertical line separator looks very similar to the digit 1 — do NOT confuse them. For example, "11|4|26" means day=11, month=4, year=26. Output the date with / as separator (e.g. "11/4/26").
- "To." line has the CUSTOMER name. Below it will be their address.
- "GST No." near the top is the CUSTOMER's GST number. "GSTIN:" near the bottom is the VENDOR's GSTIN. We only need the CUSTOMER's GST number. We don't need the VENDOR's GSTIN. The GST number is always exactly 15 alphanumeric characters starting with "27", with no special characters.
- The totals section at bottom-right has: GROSS TOTAL, Less: Discount, Total After Discount, SGST 2.5%|6%, CGST 2.5%|6%, NET TOTAL. Read each handwritten number carefully.
- CGST and SGST are ALWAYS the same value. They are either 2.5% or 6% of Total After Discount.

ARITHMETIC RULES (these MUST hold — use them to verify your reading):
- Gross Total - Discount = Total After Discount
- SGST = CGST = either 2.5% or 6% of Total After Discount
- Net Total = Total After Discount + SGST + CGST
- For each line item: Qty * Rate = Amount

Return EXACTLY this JSON structure (use "error" for any field you cannot read):

{
  "invoice_no": "The invoice number from the vendor section, or error",
  "date": "The date as written on the invoice with / separators (e.g. 11/4/26), or error",
  "customer_name": "The name after 'To.', or error",
  "customer_address": "The address after 'To.', or error",
  "customer_gstin": "The customer's GST number near 'GST No.' at top (15-digit alphanumeric starting with 27), or error",
  "gross_total": number or "error",
  "discount": number or "error",
  "total_after_discount": number or "error",
  "sgst": number or "error",
  "cgst": number or "error",
  "net_total": number or "error",
  "line_items": [
    {
      "hsn_code": "HSN code from leftmost column, or error",
      "description": "Product name/code from DESCRIPTION column, or error",
      "size": "Garment size (e.g. 38, 40, 42, 44, 46) or (M, L, XL, 2XL) or null",
      "qty": number or "error",
      "rate": number or "error",
      "amount": number or "error"
    }
  ]
}

LINE ITEMS RULES:
- The table has columns: HSN Code | DESCRIPTION | Qty. | Rate | Amount Rs. P.
- Products are garments. The first row of a product has the description. Subsequent rows for the same product show only a different size with qty/rate/amount.
- If a row has no description text, it belongs to the same product as the row above.
- Each row with a size, qty, rate, or amount should be a separate line item.
- Carefully read the handwritten sizes (usually 38, 40, 42, 44, 46, 48) and amounts.
- For each line item, verify that Qty * Rate = Amount. If it doesn't match, re-read the numbers.
- Do NOT include rows that are below the table (e.g. bank details, terms, addresses).
- Examples of descriptions will be like "Pairan", "Kurta", "Short Kurta", "H/S Print Shirt", "<word> print", "<word> plain", "Full open <word>", "Suit", etc. The actual word varies per invoice -- extract whatever is written.

NUMERIC RULES:
- All monetary values and quantities must be numbers, NOT strings.
- Read handwritten numbers with extreme care. Common confusions: 1↔7, 5↔6, 3↔8, 0↔6, 2↔Z.
- If you cannot confidently read a number, still give your best guess rather than null.
- Cross-check: Gross Total - Discount = Total After Discount. If your numbers don't add up, re-read them.

OTHER RULES:
- Other confusions: 2↔Z, 1↔I, 0↔O, 4↔A, 5↔S, 6↔G, 7↔T, 8↔B, 9↔P, 7↔A.

Return ONLY the JSON object."""

MODEL_NAME = "qwen2.5vl:3b"
