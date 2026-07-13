import serial
import csv
import datetime
import os

PORT = "COM3"
BAUD = 115200
CSV_FILE = r"C:\Users\Lucas\OneDrive\Desktop\hrv-runner\python\hrv_data.csv"

def parse_summary_line(line):
    parts = line.split(",")
    data = {}
    for part in parts:
        key, value = part.split(":")
        data[key.strip()] = value.strip()
    return data

def main():
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "rmssd_ms", "beats", "bpm",
                "feel", "miles", "duration_min", "rpe", "training_load"
            ])

        ser = serial.Serial(PORT, BAUD, timeout=10)
        print(f"Listening on {PORT}. Place your finger on the sensor.")
        print("Waiting for a completed 60-second reading...")

        while True:
            raw_line = ser.readline().decode(errors="ignore").strip()

            if raw_line.startswith("RMSSD:"):
                data = parse_summary_line(raw_line)
                rmssd = data.get("RMSSD")
                beats = data.get("beats")
                bpm = data.get("bpm")

                print(f"\nReading complete: RMSSD {rmssd}ms, {beats} beats, {bpm} BPM")

                feel = input("How do you feel today? (1-5): ")
                miles = input("Miles run yesterday (blank if none): ")
                duration = input("Run duration yesterday, in minutes (blank if none): ")
                rpe = input("Perceived effort yesterday, 1-10, 1=easy 10=max (blank if none): ")

                try:
                    training_load = float(duration) * float(rpe)
                except ValueError:
                    training_load = ""

                timestamp = datetime.datetime.now().isoformat()
                writer.writerow([
                    timestamp, rmssd, beats, bpm,
                    feel, miles, duration, rpe, training_load
                ])
                f.flush()

                print(f"Saved to {CSV_FILE}")
                break

            elif raw_line:
                print(raw_line)  # live beat output, printed but not saved

if __name__ == "__main__":
    main()