import os
import pandas as pd


def _val(v):
    """Return v as-is (preserving 0, 'error', etc.), but convert None to empty string."""
    return "" if v is None else v


def export_to_csv(invoices: list, output_dir: str) -> dict:
    """Export invoice data to CSV files.

    Args:
        invoices: List of dicts, each with keys 'filename', 'data', 'discrepancies'.
        output_dir: Directory to write CSV files into.

    Returns:
        Dict with 'summary_path' and 'items_path'.
    """
    os.makedirs(output_dir, exist_ok=True)

    summary_rows = []
    item_rows = []

    for inv in invoices:
        fn = inv["filename"]
        data = inv["data"]

        summary_rows.append({
            "File": fn,
            "Invoice No.": _val(data.get("invoice_no")),
            "Date": _val(data.get("date")),
            "Customer": _val(data.get("customer_name")),
            "Customer Address": _val(data.get("customer_address")),
            "Customer GSTIN": _val(data.get("customer_gstin")),
            "Gross Total": _val(data.get("gross_total")),
            "Discount": _val(data.get("discount")),
            "Total After Discount": _val(data.get("total_after_discount")),
            "SGST": _val(data.get("sgst")),
            "CGST": _val(data.get("cgst")),
            "Net Total": _val(data.get("net_total")),
        })

        for item in data.get("line_items", []):
            item_rows.append({
                "File": fn,
                "HSN Code": _val(item.get("hsn_code")),
                "Description": _val(item.get("description")),
                "Size": _val(item.get("size")),
                "Qty": _val(item.get("qty")),
                "Rate": _val(item.get("rate")),
                "Amount": _val(item.get("amount")),
            })

    df_summary = pd.DataFrame(summary_rows)
    df_items = pd.DataFrame(item_rows)

    summary_path = os.path.join(output_dir, "invoices_summary.csv")
    items_path = os.path.join(output_dir, "invoices_items.csv")

    df_summary.to_csv(summary_path, index=False)
    df_items.to_csv(items_path, index=False)

    paths = {"summary_path": summary_path, "items_path": items_path}

    try:
        import openpyxl  # noqa: F401
        excel_path = os.path.join(output_dir, "invoices_output.xlsx")
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_summary.to_excel(writer, sheet_name="Invoice Summary", index=False)
            df_items.to_excel(writer, sheet_name="Line Items", index=False)
            for sheet_name in writer.sheets:
                ws = writer.sheets[sheet_name]
                for col_cells in ws.columns:
                    max_len = max(
                        (len(str(c.value)) for c in col_cells if c.value), default=8
                    )
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)
        paths["excel_path"] = excel_path
    except ImportError:
        pass

    return paths
