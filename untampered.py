import cv2
import numpy as np
import hashlib
import json
import time
import os
import threading
import socket
from flask import Flask, Response, render_template_string, send_file, request

# === Config ===
OUTPUT_VIDEO = "captured_stream.avi"
DEFAULT_DURATION = 30
DEFAULT_PORT = 5000
TARGET_FPS = 20  # Target frames per second for video writer

# === Global Variables ===
frame_lock = threading.Lock()
stream_frame = None
input_sha_log = {}
output_sha_log = {}
tampered_frames = []  # Will remain empty in this version
frame_id = 0
duration = DEFAULT_DURATION
start_time = 0
is_recording = False
cap = None
out = None

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

# === Flask Endpoints ===
@app.route('/')
def home():
    return render_template_string('''
        <html><head><title>Stream Authenticator</title></head><body>
            <h1>Live Stream Authentication</h1>
            <div><a href="/video">View Stream</a></div>
            <div>
                <form action="/start_recording" method="post">
                    Duration (seconds): <input type="number" name="duration" value="''' + str(DEFAULT_DURATION) + '''" min="1" max="300">
                    <button type="submit">Start Recording</button>
                </form>
                <button onclick="downloadSHA('input')">Input SHA</button>
                <button onclick="downloadSHA('output')">Output SHA</button>
                <button onclick="downloadVideo()">Download Video</button>
            </div>
            <div>Input SHA: <span id="input-sha">-</span></div>
            <div>Output SHA: <span id="output-sha">-</span></div>
            <div>Frame Count: <span id="frame-count">0</span></div>
            <div>Tampered: <span id="tampered" style="color:green">No</span></div>
            <div>Tampered Frames: <span id="tampered-frames">None</span></div>
            <div>Recording: <span id="recording-status">No</span></div>
            <div>Elapsed: <span id="elapsed-time">0</span>s</div>
            <script>
                function update() {
                    fetch('/get_sha_logs').then(r => r.json()).then(data => {
                        document.getElementById('input-sha').textContent = data.input_sha;
                        document.getElementById('output-sha').textContent = data.output_sha;
                        document.getElementById('frame-count').textContent = data.frame_count;
                        document.getElementById('recording-status').textContent = data.is_recording ? "Yes" : "No";
                        document.getElementById('elapsed-time').textContent = data.elapsed_time;
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
    global duration, start_time
    try:
        duration = int(request.form.get('duration', DEFAULT_DURATION))
        if duration <= 0:
            duration = DEFAULT_DURATION
    except ValueError:
        duration = DEFAULT_DURATION
    
    if not is_recording:
        threading.Thread(target=record_stream).start()
        return {"message": f"Recording started for {duration} seconds"}, 200
    else:
        return {"message": "Recording already in progress"}, 400

def record_stream():
    global stream_frame, frame_id, input_sha_log, output_sha_log, tampered_frames, is_recording, cap, out, start_time, duration
    
    is_recording = True
    cap = cv2.VideoCapture(0)
    width, height = 640, 480
    
    # Set up video writer with fixed FPS
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, TARGET_FPS, (width, height))
    
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
    end_time = start_time + duration
    tampered_frames = []
    input_sha_log = {}
    output_sha_log = {}
    frame_id = 0
    
    # Main recording loop with precise timing
    while time.time() < end_time:
        frame_start_time = time.time()
        
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
        
        # Output frame (identical to input in this version)
        output_frame = frame.copy()
        cv2.putText(output_frame, timestamp, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
        
        # Compute output SHA (will be same as input)
        output_crypto = compute_cryptograph_for_frame(output_frame)
        output_sha = compute_sha256(output_crypto)
        output_sha_log[frame_id] = {"sha256": output_sha, "timestamp": timestamp}
        
        # Write frame to video file
        out.write(output_frame)
        
        with frame_lock:
            stream_frame = output_frame.copy()
        
        frame_id += 1
        
        # Calculate time to sleep to maintain frame rate
        processing_time = time.time() - frame_start_time
        target_frame_time = 1.0 / TARGET_FPS
        if processing_time < target_frame_time:
            time.sleep(target_frame_time - processing_time)
    
    # Ensure we capture the full duration
    while time.time() < end_time:
        out.write(output_frame)  # Write the last frame to fill remaining time
        time.sleep(0.01)
    
    # Clean up
    if cap.isOpened():
        cap.release()
    out.release()
    save_recording()
    is_recording = False

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
    elapsed = time.time() - start_time if is_recording and start_time > 0 else 0
    return {
        "input_sha": input_sha_log.get(latest_frame, {}).get("sha256", "-"),
        "output_sha": output_sha_log.get(latest_frame, {}).get("sha256", "-"),
        "frame_count": latest_frame,
        "tampered_frames": tampered_frames,
        "is_recording": is_recording,
        "elapsed_time": round(elapsed, 1)
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
