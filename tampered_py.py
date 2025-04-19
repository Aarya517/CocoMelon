import cv2
import numpy as np
import hashlib
import json
import time
import os
import threading
import socket
from flask import Flask, Response, render_template_string, send_file

# === Config ===
OUTPUT_VIDEO = "captured_stream.avi"
DEFAULT_DURATION = 30
DEFAULT_PORT = 5000
TAMPER_EVERY_N_FRAMES = 5
SHOW_VISUAL_TAMPER_MARKER = True

# === Global Variables ===
frame_lock = threading.Lock()
stream_frame = None
input_sha_log = {}
output_sha_log = {}
tampered_frames = []  # Track which frames were tampered
frame_id = 0
duration = DEFAULT_DURATION
start_time = 0

app = Flask(__name__)

# === SHA Computation ===
def compute_sha256(data):
    return hashlib.sha256(np.array(data, dtype=np.int32).tobytes()).hexdigest()

def compute_cryptograph_for_frame(frame, grid_size=3):
    try:
        h, w, _ = frame.shape
        grid_h, grid_w = h // grid_size, w // grid_size
        cryptographs = []
        for gy in range(grid_size):
            for gx in range(grid_size):
                grid = frame[gy*grid_h:(gy+1)*grid_h, gx*grid_w:(gx+1)*grid_w]
                cryptographs.append(int(np.sum(np.mean(grid, axis=(0, 1)))))
        return cryptographs
    except Exception as e:
        print(f"Cryptograph error: {e}")
        return []

# === Tampering Techniques ===
def subtle_pixel_shift(frame, fid):
    region = frame[100:120, 100:120]
    frame[100:120, 100:120] = np.roll(region, 1, axis=0)
    if SHOW_VISUAL_TAMPER_MARKER:
        cv2.putText(frame, f"T#{fid}", (100, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
    return frame

def lsb_tampering(frame, fid):
    frame[50:70, 50:70] ^= 1
    if SHOW_VISUAL_TAMPER_MARKER:
        cv2.rectangle(frame, (50,50), (70,70), (0,0,255), 1)
    return frame

tamper_patterns = [subtle_pixel_shift, lsb_tampering]

# === Flask Endpoints ===
@app.route('/')
def home():
    return render_template_string('''
        <html><head><title>Stream Authenticator</title></head><body>
            <h1>Live Stream Authentication</h1>
            <div><a href="/video">View Stream</a></div>
            <div>
                <button onclick="startRecording()">Start Recording</button>
                <button onclick="downloadSHA('input')">Input SHA</button>
                <button onclick="downloadSHA('output')">Output SHA</button>
                <button onclick="downloadVideo()">Download Video</button>
            </div>
            <div>Input SHA: <span id="input-sha">-</span></div>
            <div>Output SHA: <span id="output-sha">-</span></div>
            <div>Frame Count: <span id="frame-count">0</span></div>
            <div>Tampered: <span id="tampered" style="color:green">No</span></div>
            <div>Tampered Frames: <span id="tampered-frames">None</span></div>
            <script>
                function update() {
                    fetch('/get_sha_logs').then(r => r.json()).then(data => {
                        document.getElementById('input-sha').textContent = data.input_sha;
                        document.getElementById('output-sha').textContent = data.output_sha;
                        document.getElementById('frame-count').textContent = data.frame_count;
                        const tamperedElem = document.getElementById('tampered');
                        if (data.input_sha !== data.output_sha && data.output_sha !== '-') {
                            tamperedElem.textContent = 'YES';
                            tamperedElem.style.color = 'red';
                        } else {
                            tamperedElem.textContent = 'NO';
                            tamperedElem.style.color = 'green';
                        }
                        document.getElementById('tampered-frames').textContent = 
                            data.tampered_frames.length ? data.tampered_frames.join(', ') : 'None';
                    });
                }
                function startRecording() { fetch('/start_recording', {method: 'POST'}); }
                function downloadSHA(type) { window.location = '/download_sha_' + type; }
                function downloadVideo() { window.location = '/download_video'; }
                setInterval(update, 500);
            </script>
        </body></html>
    ''')

@app.route('/video')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if stream_frame is not None:
                    _, jpeg = cv2.imencode('.jpg', stream_frame)
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            time.sleep(0.03)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_recording', methods=['POST'])
def start_recording():
    threading.Thread(target=record_stream).start()
    return {"message": f"Recording started for {DEFAULT_DURATION} seconds"}, 200

def record_stream():
    global stream_frame, frame_id, input_sha_log, output_sha_log, tampered_frames
    
    cap = cv2.VideoCapture(0)
    width, height = 640, 480
    if not cap.isOpened():
        print("No camera - using test pattern")
        test_pattern = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(test_pattern, "TEST PATTERN", (150, height//2), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,255), 2)
        ret, frame = True, test_pattern
    else:
        ret, frame = cap.read()
        if ret:
            height, width = frame.shape[:2]
    
    start_time = time.time()
    tampered_frames = []
    input_sha_log = {}
    output_sha_log = {}
    frame_id = 0
    
    while time.time() - start_time < DEFAULT_DURATION:
        if cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Input frame (original)
        input_frame = frame.copy()
        cv2.putText(input_frame, timestamp, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
        input_crypto = compute_cryptograph_for_frame(input_frame)
        input_sha = compute_sha256(input_crypto)
        input_sha_log[frame_id] = {"sha256": input_sha, "timestamp": timestamp}
        
        # Output frame (potentially tampered)
        output_frame = frame.copy()
        cv2.putText(output_frame, timestamp, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
        
        # Apply tampering periodically
        if frame_id % TAMPER_EVERY_N_FRAMES == 0 and frame_id > 0:
            pattern_idx = frame_id % len(tamper_patterns)
            output_frame = tamper_patterns[pattern_idx](output_frame.copy(), frame_id)
        
        # Compute output SHA
        output_crypto = compute_cryptograph_for_frame(output_frame)
        output_sha = compute_sha256(output_crypto)
        output_sha_log[frame_id] = {"sha256": output_sha, "timestamp": timestamp}
        
        # Detect tampering
        if input_sha != output_sha:
            tampered_frames.append(frame_id)
            cv2.putText(output_frame, f"TAMPERED", (width-200, 50), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
        
        with frame_lock:
            stream_frame = output_frame.copy()
        
        frame_id += 1
        time.sleep(0.05)
    
    if cap.isOpened():
        cap.release()
    save_recording()

def save_recording():
    try:
        with open("input_sha_log.json", "w") as f:
            json.dump(input_sha_log, f)
        with open("output_sha_log.json", "w") as f:
            json.dump(output_sha_log, f)
        print(f"Saved SHA logs for {frame_id} frames")
    except Exception as e:
        print(f"Error saving logs: {e}")

@app.route('/get_sha_logs')
def get_sha_logs():
    latest_frame = max(input_sha_log.keys()) if input_sha_log else 0
    return {
        "input_sha": input_sha_log.get(latest_frame, {}).get("sha256", "-"),
        "output_sha": output_sha_log.get(latest_frame, {}).get("sha256", "-"),
        "frame_count": latest_frame,
        "tampered_frames": tampered_frames
    }

@app.route('/download_sha_input')
def download_sha_input():
    return Response(json.dumps(input_sha_log), mimetype="application/json",
                   headers={"Content-Disposition": "attachment;filename=input_sha.json"})

@app.route('/download_sha_output')
def download_sha_output():
    return Response(json.dumps(output_sha_log), mimetype="application/json",
                   headers={"Content-Disposition": "attachment;filename=output_sha.json"})

@app.route('/download_video')
def download_video():
    if os.path.exists(OUTPUT_VIDEO):
        return send_file(OUTPUT_VIDEO, as_attachment=True)
    return "Video not available", 404

if __name__ == "__main__":
    port = DEFAULT_PORT
    while port < DEFAULT_PORT + 100:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            port += 1
