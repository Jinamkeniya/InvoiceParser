import os
import uuid
import glob
import logging

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, flash,
)

from extraction.vlm_extractor import extract_invoice
from export.csv_export import export_to_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("invoices")
    if not files or all(f.filename == "" for f in files):
        flash("No files selected.", "error")
        return redirect(url_for("index"))

    job_id = str(uuid.uuid4())[:8]
    job_upload_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_upload_dir, exist_ok=True)

    saved_paths = []
    for f in files:
        if f and f.filename and _allowed_file(f.filename):
            safe_name = f.filename.replace(" ", "_")
            path = os.path.join(job_upload_dir, safe_name)
            f.save(path)
            saved_paths.append((safe_name, path))

    if not saved_paths:
        flash("No valid image files uploaded (JPG/PNG only).", "error")
        return redirect(url_for("index"))

    invoices = []
    for filename, path in saved_paths:
        logger.info("Processing: %s", filename)

        data = extract_invoice(path)
        discrepancies = data.pop("_discrepancies", [])

        invoices.append({
            "filename": filename,
            "data": data,
            "discrepancies": discrepancies,
        })

    job_results_dir = os.path.join(RESULTS_DIR, job_id)
    paths = export_to_csv(invoices, job_results_dir)

    return render_template(
        "results.html",
        invoices=invoices,
        job_id=job_id,
        has_excel="excel_path" in paths,
    )


@app.route("/download/<job_id>/<filetype>")
def download(job_id, filetype):
    job_dir = os.path.join(RESULTS_DIR, job_id)
    if not os.path.isdir(job_dir):
        flash("Results not found.", "error")
        return redirect(url_for("index"))

    if filetype == "summary":
        return send_file(
            os.path.join(job_dir, "invoices_summary.csv"),
            as_attachment=True,
            download_name="invoices_summary.csv",
        )
    elif filetype == "items":
        return send_file(
            os.path.join(job_dir, "invoices_items.csv"),
            as_attachment=True,
            download_name="invoices_items.csv",
        )
    elif filetype == "excel":
        excel_path = os.path.join(job_dir, "invoices_output.xlsx")
        if os.path.exists(excel_path):
            return send_file(
                excel_path,
                as_attachment=True,
                download_name="invoices_output.xlsx",
            )
    flash("File not found.", "error")
    return redirect(url_for("index"))


@app.route("/process-images", methods=["POST"])
def process_images_dir():
    """Process all images in the local images/ directory (for testing)."""
    image_dir = os.path.join(os.path.dirname(__file__), "images")
    extensions = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")

    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(image_dir, ext)))
    image_files = sorted(set(image_files))

    if not image_files:
        flash("No images found in images/ directory.", "error")
        return redirect(url_for("index"))

    job_id = str(uuid.uuid4())[:8]
    invoices = []

    for img_path in image_files:
        filename = os.path.basename(img_path)
        logger.info("Processing: %s", filename)

        data = extract_invoice(img_path)
        discrepancies = data.pop("_discrepancies", [])

        invoices.append({
            "filename": filename,
            "data": data,
            "discrepancies": discrepancies,
        })

    job_results_dir = os.path.join(RESULTS_DIR, job_id)
    paths = export_to_csv(invoices, job_results_dir)

    return render_template(
        "results.html",
        invoices=invoices,
        job_id=job_id,
        has_excel="excel_path" in paths,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
