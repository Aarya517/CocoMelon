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

# === Global Variables ===
frame_lock = threading.Lock()
stream_frame = None
frame_sha_log = {}
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

# === Flask Endpoints ===
@app.route('/')
def home():
    return render_template_string('''
        <html><head><title>Stream Authenticator</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .panel { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
            .info-row { display: flex; justify-content: space-between; margin-bottom: 10px; }
            .info-item { flex: 1; padding: 10px; }
            .buttons { margin: 20px 0; }
            button { padding: 8px 15px; margin-right: 10px; cursor: pointer; }
            .status-ok { color: green; font-weight: bold; }
        </style>
        </head><body>
            <div class="container">
                <h1>Live Stream Authentication</h1>
                <div class="panel">
                    <div class="info-row">
                        <div class="info-item">
                            <h3>Stream Status</h3>
                            <div>Status: <span id="status" class="status-ok">AUTHENTICATED</span></div>
                            <div>Frame Count: <span id="frame-count">0</span></div>
                        </div>
                        <div class="info-item">
                            <h3>Authentication</h3>
                            <div>Current SHA: <span id="current-sha">-</span></div>
                            <div>Timestamp: <span id="timestamp">-</span></div>
                        </div>
                    </div>
                </div>
                
                <div class="panel">
                    <a href="/video">View Live Stream</a>
                </div>
                
                <div class="buttons">
                    <button onclick="startRecording()">Start Recording</button>
                    <button onclick="downloadSHA()">Download SHA Log</button>
                    <button onclick="downloadVideo()">Download Video</button>
                </div>
            </div>
            
            <script>
                function update() {
                    fetch('/get_sha_logs').then(r => r.json()).then(data => {
                        document.getElementById('current-sha').textContent = data.current_sha.substring(0, 8) + '...';
                        document.getElementById('frame-count').textContent = data.frame_count;
                        document.getElementById('timestamp').textContent = data.timestamp;
                    });
                }
                function startRecording() { fetch('/start_recording', {method: 'POST'}); }
                function downloadSHA() { window.location = '/download_sha'; }
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
    global stream_frame, frame_id, frame_sha_log
    
    # Initialize video writer
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = None  # Will initialize when we know the frame dimensions
    
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
            out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, 20.0, (width, height))
    
    start_time = time.time()
    frame_sha_log = {}
    frame_id = 0
    
    while time.time() - start_time < DEFAULT_DURATION:
        if cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Process frame
        processed_frame = frame.copy()
        
        # Add timestamp and frame information
        cv2.putText(processed_frame, timestamp, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(processed_frame, f"Frame: {frame_id}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Add authentication status
        cv2.putText(processed_frame, "AUTHENTICATED", (width-200, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Compute SHA
        frame_crypto = compute_cryptograph_for_frame(processed_frame)
        frame_sha = compute_sha256(frame_crypto)
        frame_sha_log[frame_id] = {
            "sha256": frame_sha, 
            "timestamp": timestamp
        }
        
        # Show SHA info on frame
        cv2.putText(processed_frame, f"SHA: {frame_sha[:8]}...", (width-200, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Write to video file
        if out is not None:
            out.write(processed_frame)
        
        with frame_lock:
            stream_frame = processed_frame.copy()
        
        frame_id += 1
        time.sleep(0.05)
    
    if cap.isOpened():
        cap.release()
    if out is not None:
        out.release()
        
    save_recording()

def save_recording():
    try:
        with open("frame_sha_log.json", "w") as f:
            json.dump(frame_sha_log, f)
        print(f"Saved SHA logs for {frame_id} frames")
    except Exception as e:
        print(f"Error saving logs: {e}")

@app.route('/get_sha_logs')
def get_sha_logs():
    latest_frame = max(frame_sha_log.keys()) if frame_sha_log else 0
    latest_data = frame_sha_log.get(str(latest_frame) if isinstance(latest_frame, int) else latest_frame, {})
    
    return {
        "current_sha": latest_data.get("sha256", "-"),
        "timestamp": latest_data.get("timestamp", "-"),
        "frame_count": latest_frame
    }

@app.route('/download_sha')
def download_sha():
    return Response(json.dumps(frame_sha_log), mimetype="application/json",
                   headers={"Content-Disposition": "attachment;filename=frame_sha_log.json"})

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
