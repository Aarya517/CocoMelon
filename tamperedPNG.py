import cv2
import numpy as np
import hashlib
import json
import time
import os
from flask import Flask, Response, render_template_string, jsonify, send_file
import threading

# === Config ===
FRAME_DIR = "frames"
INPUT_SHA_LOG = "input_sha_log.json"
TAMPERED_SHA_LOG = "tampered_sha_log.json"
OUTPUT_SHA_LOG = "output_sha_log.json"
DEFAULT_DURATION = 10
GRID_SIZE = 3
OUTPUT_VIDEO_PATH = "reconstructed_video.avi"

# === SHA + Cryptograph ===
def compute_sha256(data):
    hash_object = hashlib.sha256()
    hash_object.update(np.array(data, dtype=np.int32).tobytes())
    return hash_object.hexdigest()

def compute_cryptograph_for_frame(frame, grid_size=GRID_SIZE):
    try:
        h, w, _ = frame.shape
        grid_h, grid_w = h // grid_size, w // grid_size
        frame_cryptographs = []

        for gy in range(grid_size):
            for gx in range(grid_size):
                start_y = gy * grid_h
                start_x = gx * grid_w
                grid = frame[start_y:start_y + grid_h, start_x:start_x + grid_w]
                mean_pixel = np.mean(grid, axis=(0, 1))
                value = int(np.sum(mean_pixel))
                cryptograph = value
                frame_cryptographs.append(cryptograph)
        return frame_cryptographs
    except Exception as e:
        print(f"Error computing cryptograph: {e}")
        return []

# === SHA Extraction ===
def extract_and_log_sha_from_images(folder_path, output_json):
    log, frame_id, combined = {}, 0, []
    frame_files = sorted([f for f in os.listdir(folder_path) if f.endswith('.png')])
    for filename in frame_files:
        frame_path = os.path.join(folder_path, filename)
        frame = cv2.imread(frame_path)
        if frame is None:
            continue
        cryptograph = compute_cryptograph_for_frame(frame)
        sha = compute_sha256(cryptograph)
        log[str(frame_id)] = {"sha256": sha}
        combined.extend(cryptograph)
        print(f"[Extract {frame_id}] SHA: {sha}")
        frame_id += 1
    with open(output_json, 'w') as f:
        json.dump(log, f, indent=4)
    combined_sha = compute_sha256(combined)
    print(f"[✓] SHA log written to {output_json}")
    print(f"[✓] Combined SHA: {combined_sha}")
    return combined_sha

# === Flask Setup ===
app = Flask(__name__)
stream_frame = None
sha_log = {}
frame_id = 0
duration = DEFAULT_DURATION
start_time = 0
input_combined_sha = ""
output_combined_sha = ""

def clear_directory(path):
    if os.path.exists(path):
        for f in os.listdir(path):
            os.remove(os.path.join(path, f))
    else:
        os.makedirs(path)

@app.route('/')
def home():
    return render_template_string('''
        <html><head><title>Live Stream</title></head><body>
        <h2>Live Stream: <a href="/video">View Video</a></h2>
        <button onclick="startRecording()">Start Recording</button>
        <button onclick="compareSHAs()">Compare SHAs</button>
        <a href="/download_video" target="_blank">Download Reconstructed Video</a>
        <p>SHA Log: <span id="sha-log">Waiting...</span></p>
        <p id="compare-result"></p>
        <script>
        function startRecording() {
            fetch('/start_recording', {method: 'POST'})
            .then(r => r.json()).then(d => alert(d.message));
        }
        function compareSHAs() {
            fetch('/compare_shas').then(r => r.json()).then(d => {
                document.getElementById('compare-result').innerText =
                `Real Combined SHA: ${d.real_combined_sha} | Tampered Combined SHA: ${d.tampered_combined_sha} | Equal: ${d.equal}`;
            });
        }
        setInterval(() => {
            fetch('/get_sha_log').then(r => r.json()).then(d => {
                document.getElementById('sha-log').innerText = d.sha;
            });
        }, 1000);
        </script></body></html>
    ''')

@app.route('/video')
def video_feed():
    def generate():
        global stream_frame
        while True:
            if stream_frame is not None:
                _, jpeg = cv2.imencode('.jpg', stream_frame)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_recording', methods=['POST'])
def start_recording():
    threading.Thread(target=record_and_generate_sha, daemon=True).start()
    return {"message": "Recording started!"}

def record_and_generate_sha():
    global stream_frame, frame_id, sha_log, start_time, input_combined_sha, output_combined_sha
    print("[*] Starting recording...")
    cap = cv2.VideoCapture(0)
    for _ in range(30):
        ret, frame = cap.read()
        if ret: break
        time.sleep(0.05)
    if not ret:
        print("[!] Webcam access failed.")
        return

    frames, sha_log, frame_id, combined = [], {}, 0, []
    start_time = time.time()
    clear_directory(FRAME_DIR)

    while cap.isOpened():
        if time.time() - start_time >= duration:
            break
        ret, frame = cap.read()
        if not ret:
            break
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2, cv2.LINE_AA)
        stream_frame = frame.copy()
        frames.append(frame)
        cryptograph = compute_cryptograph_for_frame(frame)
        sha = compute_sha256(cryptograph)
        sha_log[str(frame_id)] = {"timestamp": timestamp, "sha256": sha}
        combined.extend(cryptograph)
        print(f"[Frame {frame_id}] SHA: {sha}")
        frame_id += 1
    cap.release()

    print(f"[*] Recording done ({duration}s)")
    input_combined_sha = compute_sha256(combined)
    save_frames_and_sha(frames)

def save_frames_and_sha(frames):
    for idx, f in enumerate(frames):
        cv2.imwrite(os.path.join(FRAME_DIR, f"frame_{idx:04d}.png"), f)
    with open(INPUT_SHA_LOG, 'w') as f:
        json.dump(sha_log, f, indent=4)
    print(f"[✓] Frames and SHA log saved to {FRAME_DIR} and {INPUT_SHA_LOG}")
    create_tampered_sha_log(sha_log)
    reconstruct_video_from_frames()
    global output_combined_sha
    output_combined_sha = extract_and_log_sha_from_images(FRAME_DIR, OUTPUT_SHA_LOG)

def create_tampered_sha_log(original_log):
    tampered_log = {}
    for frame_id, data in original_log.items():
        sha = data["sha256"]
        tampered_sha = sha[:5] + ('A' if sha[5] != 'A' else 'B') + sha[6:]
        tampered_log[frame_id] = {
            "timestamp": data["timestamp"],
            "sha256": tampered_sha
        }
    with open(TAMPERED_SHA_LOG, 'w') as f:
        json.dump(tampered_log, f, indent=4)
    print("[!] Tampered SHA log saved as tampered_sha_log.json")

def reconstruct_video_from_frames():
    frame_files = sorted([f for f in os.listdir(FRAME_DIR) if f.endswith('.png')])
    if not frame_files:
        print("[!] No frames found for video reconstruction.")
        return
    first_frame = cv2.imread(os.path.join(FRAME_DIR, frame_files[0]))
    height, width, _ = first_frame.shape
    out = cv2.VideoWriter(OUTPUT_VIDEO_PATH, cv2.VideoWriter_fourcc(*'MJPG'), 20, (width, height))
    for filename in frame_files:
        frame = cv2.imread(os.path.join(FRAME_DIR, filename))
        if frame is not None:
            out.write(frame)
    out.release()
    print(f"[✓] Reconstructed video saved to {OUTPUT_VIDEO_PATH}")

@app.route('/download_video')
def download_video():
    if os.path.exists(OUTPUT_VIDEO_PATH):
        return send_file(OUTPUT_VIDEO_PATH, as_attachment=True)
    return {"error": "Video not available."}, 404

@app.route('/get_sha_log')
def get_sha_log():
    latest = sha_log.get(str(frame_id-1), {}).get("sha256", "No SHA yet")
    return {"sha": latest}

@app.route('/compare_shas')
def compare_shas():
    with open(INPUT_SHA_LOG) as f:
        input_log = json.load(f)
    with open(TAMPERED_SHA_LOG) as f:
        tampered_log = json.load(f)

    input_combined = ''.join([d["sha256"] for d in input_log.values()])
    tampered_combined = ''.join([d["sha256"] for d in tampered_log.values()])

    input_sha = hashlib.sha256(input_combined.encode()).hexdigest()
    tampered_sha = hashlib.sha256(tampered_combined.encode()).hexdigest()

    return jsonify({
        "real_combined_sha": input_sha,
        "tampered_combined_sha": tampered_sha,
        "equal": input_sha == tampered_sha
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
