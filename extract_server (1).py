from flask import Flask, request, jsonify
import tempfile
import os
from flask_cors import CORS
from extractor import process_pdf

app = Flask(__name__)
CORS(app)

@app.route("/extract", methods=["POST"])
def extract():

    print("\n========================")
    print("NEW EXTRACTION REQUEST")
    print("========================")

    if "file" not in request.files:

        print("No file uploaded")

        return jsonify({
            "success": False,
            "error": "No file uploaded"
        }), 400

    pdf = request.files["file"]

    print("Uploaded file:", pdf.filename)

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf"
        ) as tmp:

            pdf.save(tmp.name)

            print("Saved temp PDF:", tmp.name)

            task_dir = process_pdf(tmp.name)

            print("Extraction complete")
            print("Task dir:", task_dir)

        return jsonify({
            "success": True,
            "task_dir": task_dir
        })

    except Exception as e:

        print("EXTRACTION ERROR:")
        print(str(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=9700,
        debug=True
    )