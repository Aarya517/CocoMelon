import cv2
import numpy as np
import json
import os
import hashlib

# Ask for video input paths
def get_video_path(prompt):
    video_path = input(prompt)
    while not os.path.exists(video_path):
        print("Invalid path. Please try again.")
        video_path = input(prompt)
    return video_path

# Function to compute SHA-256 hash of a cryptograph
def compute_sha256(cryptograph):
    hash_object = hashlib.sha256()
    # Convert cryptograph list to bytes properly (using np.int32 or np.int64)
    hash_object.update(np.array(cryptograph, dtype=np.int32).tobytes())  # Use int32 for larger values
    return hash_object.hexdigest()

# Compute cryptograph using mean of each grid instead of just the center pixel
def compute_cryptograph_for_frame(frame, grid_size=3):
    h, w, _ = frame.shape
    grid_h, grid_w = h // grid_size, w // grid_size
    frame_cryptographs = []

    for gy in range(grid_size):
        for gx in range(grid_size):
            start_y = gy * grid_h
            start_x = gx * grid_w
            grid = frame[start_y:start_y + grid_h, start_x:start_x + grid_w]

            mean_pixel = np.mean(grid, axis=(0, 1))  # More robust than center pixel
            value = int(np.sum(mean_pixel))
            cryptograph = 0
            if value % 3 == 0 and value % 11 == 0:
                cryptograph += value
            if value % 5 == 0:
                cryptograph *= 5
            frame_cryptographs.append(cryptograph)

    return frame_cryptographs

# Extract cryptographs from a video and compute SHA-256 hash
def analyze_video(video_path):
    cap = cv2.VideoCapture(video_path)
    cryptograph_data = {}
    sha_data = {}
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.resize(frame, (300, 300))  # Standardize frame size
        cryptograph = compute_cryptograph_for_frame(frame)
        sha_hash = compute_sha256(cryptograph)
        
        cryptograph_data[f"frame_{frame_count}"] = cryptograph
        sha_data[f"frame_{frame_count}"] = sha_hash
        frame_count += 1

    cap.release()
    return cryptograph_data, sha_data

# Compare with tolerance to ignore minor pixel-level noise
def compare_cryptographs(original, tampered, tolerance=10):
    differences = []
    matched_frames = set(original.keys()).intersection(set(tampered.keys()))

    for frame_key in matched_frames:
        orig_vals = np.array(original[frame_key])
        tamp_vals = np.array(tampered[frame_key])
        diff = np.abs(orig_vals - tamp_vals)
        num_diffs = np.sum(diff > tolerance)
        if num_diffs > 0:
            differences.append((frame_key, num_diffs))

    return differences

# Compare SHA hashes to check integrity
def compare_sha_hashes(original_sha, tampered_sha):
    hash_differences = []
    matched_frames = set(original_sha.keys()).intersection(set(tampered_sha.keys()))

    for frame_key in matched_frames:
        if original_sha[frame_key] != tampered_sha[frame_key]:
            hash_differences.append(frame_key)

    return hash_differences

# Verdict logic
def is_tampered(differences, total_frames, threshold_ratio=0.1):
    return len(differences) / total_frames > threshold_ratio

# -----------------------------
# 🔽 Main Execution
# -----------------------------

original_video_path = get_video_path("Enter path to the original video: ")
tampered_video_path = get_video_path("Enter path to the second (possibly tampered) video: ")

original_cryptographs, original_sha = analyze_video(original_video_path)
tampered_cryptographs, tampered_sha = analyze_video(tampered_video_path)

# Frame count checks
frame_count_original = len(original_cryptographs)
frame_count_tampered = len(tampered_cryptographs)
common_frame_count = min(frame_count_original, frame_count_tampered)

print(f"\nOriginal video frames: {frame_count_original}")
print(f"Second video frames:   {frame_count_tampered}")
print(f"Frames compared:       {common_frame_count}")

# Compare cryptographs
differences = compare_cryptographs(original_cryptographs, tampered_cryptographs, tolerance=10)

# Compare SHA hashes
hash_differences = compare_sha_hashes(original_sha, tampered_sha)

# Final result
if is_tampered(differences, common_frame_count) or len(hash_differences) > 0:
    print("\n🟥 Verdict: The second video is likely TAMPERED.")
else:
    print("\n🟩 Verdict: The second video appears to be AUTHENTIC.")

# Save outputs if needed
with open("original_video_cryptographs.json", "w") as f:
    json.dump(original_cryptographs, f, indent=2)

with open("tampered_video_cryptographs.json", "w") as f:
    json.dump(tampered_cryptographs, f, indent=2)

with open("original_video_sha_hashes.json", "w") as f:
    json.dump(original_sha, f, indent=2)

with open("tampered_video_sha_hashes.json", "w") as f:
    json.dump(tampered_sha, f, indent=2)

if differences or hash_differences:
    print(f"\n🔍 {len(differences)} frame(s) had differences exceeding tolerance.")
    print(f"🔍 {len(hash_differences)} frame(s) had SHA hash mismatches.")
else:
    print("\n✅ No significant differences found.")
