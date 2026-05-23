import fitz
import os
from pathlib import Path
import re
from collections import defaultdict
from PIL import Image
import io
import requests
import base64
import mimetypes
import json
from flask_cors import CORS
from minio import Minio
import io

# ── MinIO config ──────────────────────────────────────────
MINIO_ENDPOINT   = "10.224.235.31:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "1234@Qwer"
MINIO_BUCKET     = "pm-photos"
MINIO_SECURE     = False

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)

if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)

SERVER_URL = "http://10.130.154.133:8000/v1/chat/completions"
MODEL_NAME = "./"
pdf_dir = Path("./PM Reports")
prompt_path = "prompt.txt"


def encode_image(image_path):
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    return f"data:{mime};base64,{b64}"


def load_prompt(prompt_path):
    """Load prompt text from an external file."""
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def extract_fields_to_minio(pil_image, prompt_path, task_id, inspection_num, img_index):
    """Send image to model, get JSON metadata, upload JSON to MinIO."""
    
    prompt = load_prompt(prompt_path)
    
    # Encode PIL image to base64 (no temp file needed)
    buf = io.BytesIO()
    pil_image.save(buf, "JPEG", quality=95)
    b64 = base64.b64encode(buf.getvalue()).decode()
    data_url = f"data:image/jpeg;base64,{b64}"

    payload = {
        "model": MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    }

    res = requests.post(SERVER_URL, json=payload)
    res.raise_for_status()
    content = res.json()["choices"][0]["message"]["content"]

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {}

    result = {
        "date_time": result.get("date_time", "unknown"),
        "lat":       result.get("lat", "unknown"),
        "lng":       result.get("lng", "unknown"),
        "taskID":    result.get("taskID", "unknown"),
    }

    # Upload JSON to MinIO
    json_bytes = json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")
    json_object_name = f"photos/{task_id}/{inspection_num}/{img_index}.json"
    
    minio_client.put_object(
        MINIO_BUCKET,
        json_object_name,
        io.BytesIO(json_bytes),
        len(json_bytes),
        content_type="application/json",
    )
    print(f"Uploaded JSON to MinIO: {json_object_name}")
    return result

def taskID_extracator(docs):

    task_id = None
    
    text = docs[0].get_text("rawdict")
    spans = []
    for block in text["blocks"]:
        if block["type"] != 0:
            continue

        for line in block["lines"]:
            for span in line["spans"]:
                if "chars" not in span or not span["chars"]:
                    continue

                span_text = "".join(c["c"] for c in span["chars"])
                if span_text:
                    spans.append(span_text)

    for i, s in enumerate(spans):
        if s == "Task ID:":
            if i + 1 < len(spans):
                candidate = spans[i + 1].strip()
                if re.fullmatch(r"PM-\d{8}-\d+", candidate):
                    task_id = candidate
                    break

    return task_id

def ok_not_ok_locations(docs):
    photo_markers_by_page = {}

    for page_num, page in enumerate(docs):
        text = page.get_text("rawdict")

        photo_markers = []

        for block in text["blocks"]:
            if block["type"] != 0:
                continue

            for line in block["lines"]:
                for span in line["spans"]:
                    if "chars" not in span or not span["chars"]:
                        continue

                    span_text = "".join(c["c"] for c in span["chars"])

                    # detect "photo"
                    if span_text.strip().lower() == "ok" or span_text.strip().lower() == "not ok":
                        y = span["bbox"][1]  # top y
                        photo_markers.append({
                            "word": span_text,
                            "y": y
                        })

        photo_markers_by_page[page_num] = photo_markers

    god_list = []
    threshold = 0.5

    for page, item in photo_markers_by_page.items():
        oks = [c['y'] for c in item if c['word'] == 'OK']
        not_oks = [c['y'] for c in item if c['word'] == 'Not OK']
        
        for ok_y in oks:
            for notok_y in not_oks:
                if abs(ok_y - notok_y) <= threshold:
                    god_list.append({
                        'page': page,
                        'ok_y': ok_y,
                        'not_ok_y': notok_y
                    })

    # Transform the data
    ok_notok_data = defaultdict(list)
    for item in god_list:
        ok_notok_data[item['page']].append({
            'ok_y': item['ok_y'],
            'not_ok_y': item['not_ok_y']
        })

    # Convert to regular dict
    ok_notok_data = dict(ok_notok_data)

    result = defaultdict(list)
    i = 0

    for item in god_list:
        page = item['page']
        
        # increment FIRST
        i += 1
        
        result[page].append({
            'inspection': i,
            'ok_y': item['ok_y'],
            'not_ok_y': item['not_ok_y']
        })

    result = dict(result)
    ok_notok_data = result

    return ok_notok_data

def cropper(image):
    height = image.height
    cropped = image.crop((0, height-300, 600, height))
    return cropped


def image_extractor(docs, images_path, ok_notok_data, prompt_path):

    #os.makedirs(images_path, exist_ok=True)

    inspection_counters = defaultdict(int)
    last_marker = None  # track last marker across pages

    for page_num, page in enumerate(docs):

        images_info = page.get_image_info(xrefs=True)
        photo_markers = sorted(
            ok_notok_data.get(page_num, []),
            key=lambda x: x["ok_y"]
        )

        for info in images_info:
            xref = info["xref"]
            x0, y0, x1, y1 = info["bbox"]

            width = x1 - x0
            height = y1 - y0

            if width < 10 or height < 10:
                continue

            image_y = y0

            matched_inspection = None

            for i in range(len(photo_markers)):
                current_marker = photo_markers[i]
                next_marker = photo_markers[i + 1] if i + 1 < len(photo_markers) else None

                if image_y > current_marker["ok_y"]:
                    if next_marker is None or image_y < next_marker["ok_y"]:
                        matched_inspection = current_marker["inspection"]
                        break

            # fallback: use last marker from a previous page
            if matched_inspection is None:
                if last_marker is not None:
                    matched_inspection = last_marker["inspection"]
                else:
                    continue  # no previous marker at all, skip

            inspection_counters[matched_inspection] += 1
            index = inspection_counters[matched_inspection]
            filename_index = f"{index}"   # just the number, e.g. "1"
            
            extracted = docs.extract_image(xref)
            image_bytes = extracted["image"]
            image = Image.open(io.BytesIO(image_bytes))
            rgb = image.convert("RGB")
            
            # ── Upload JPEG to MinIO ──────────────────────────────────
            img_buffer = io.BytesIO()
            rgb.save(img_buffer, "JPEG", quality=95)
            img_buffer.seek(0)
            img_size = img_buffer.getbuffer().nbytes
            object_name = f"photos/{images_path}/{matched_inspection}/{filename_index}.jpg"
            
            minio_client.put_object(
                MINIO_BUCKET,
                object_name,
                img_buffer,
                img_size,
                content_type="image/jpeg",
            )
            print(f"Uploaded to MinIO: {object_name}")
            
            # ── Extract metadata and upload JSON to MinIO ─────────────
            extract_fields_to_minio(rgb, prompt_path, images_path, matched_inspection, filename_index)

        # update last_marker to the last marker seen on this page
        if photo_markers:
            last_marker = photo_markers[-1]

# for pdf_file in pdf_dir.glob("*.pdf"):
#     pdf_filename = pdf_file.name
#     full_path = os.path.join(pdf_dir, pdf_filename)
#     print("Processing:", full_path)
#     docs = fitz.open(full_path)
#     dir_name = taskID_extracator(docs=docs)
#     oknotok_data = ok_not_ok_locations(docs=docs)
#     image_extractor(docs=docs, images_path=dir_name, ok_notok_data=oknotok_data, prompt_path=prompt_path)



def process_pdf(pdf_path):
    
    print("Processing:", pdf_path)

    docs = fitz.open(pdf_path)

    dir_name = taskID_extracator(docs=docs)
    print("Detected task ID:", dir_name)
    if not dir_name:
        raise Exception("Task ID not found")

    oknotok_data = ok_not_ok_locations(docs=docs)
    print("Detected rows:", oknotok_data)
    image_extractor(
        docs=docs,
        images_path=dir_name,
        ok_notok_data=oknotok_data,
        prompt_path=prompt_path
    )
    print("Saved image:", pdf_path)
    return dir_name


if __name__ == "__main__":

    for pdf_file in pdf_dir.glob("*.pdf"):

        pdf_filename = pdf_file.name

        full_path = os.path.join(pdf_dir, pdf_filename)

        process_pdf(full_path)



