# hrv-runner

A wearable heart rate variability (HRV) monitor built to track running recovery with custom signal-processing firmware, a Python data pipeline and dashboard, and an AI recovery layer.

`Arduino C++` `Python` `Flask` `Claude API` `Signal Processing`

> Can measuring beat-to-beat variation in heart rate to reveal the stress on a runner's body, and whether they are actually recovered or not.

## Contents
- [Why I built this](#why-i-built-this)
- [How it works](#how-it-works)
- [Getting here: what didn't work](#getting-here-what-didnt-work)
- [Key finding](#key-finding)
- [Data analysis](#data-analysis)
- [Known limitations](#known-limitations)
- [Build it yourself](#build-it-yourself)
- [Stack](#stack)

## Why I built this

My 1600m times dropped noticeably during my junior track season, and I was later diagnosed with iron deficiency. The deficiency suppresses recovery in runners unknowingly until it already hurts performance. I had already dealt with iron deficiency another time during my sophomore cross country season.  This got me curious about how we can actually measure running recovery instead of just guessing on how we feel. The project measures HRV every morning and uses it, alongside training and sleep data, to give an individualized recovery read and dashboard for any runner who wants to build one.

## How it works

The sensor takes a reading, the firmware turns it into a heartrate variability number to measure stress, this data is collected with other metrics like sleep and run intensity, and a program provides an interactive dashboard with training recommendations.

**Sensor hardware.** A MAX30101/MAX32664 pulse oximeter connects to an Arduino Mega 2560 over I2C. The MAX32664 has its own onboard processor and a built-in BPM output, but the firmware bypasses that and reads the raw infrared signal directly, running my own signal processing instead.

**Signal processing (Arduino C++).** The raw signal is dominated by a large & slowly drifting baseline with the real pulse riding on top as a small wave. Two moving averages at different speeds strip the baseline out and isolate the pulse. An adaptive threshold and maximum peak detector find individual heartbeats with a refractory period, a warmup period, and a median consistency check to reject invalid beats. The firmware calculates RMSSD (the standard clinical measure of HRV) from the differences in timing between valid beats over a one minute reading.

**Logging (Python).** A script gets the Arduino's serial output, waits for a completed reading, and asks the user for a subjective feel score, hours of sleep, and the previous day's training details. Training load is calculated as duration × perceived effort (RPE). This is a standard sports science method that captures training intensity instead of just mileage. Every reading is added to a CSV file.

**Dashboard (Flask + Chart.js).** A local web app reads the CSV and renders summaries of metrics (latest HRV, personal baseline, training load, days logged) and interactive charts for HRV, training load, and feel score over time.

**Recovery assessment (Claude API).** The dashboard computes a personal baseline from days the runner reports feeling well-recovered, and sends that along with the day's reading, recent training context and an outlier/anomaly check to the Claude API. The response is a short, specific recovery read reasoned from the runner's own trend, not a fixed population threshold for HRV.

## Getting here: what didn't work

The current design is the result of trial and error.

**First sensor** I started with a different MAX30102 sensor, wired through a breadboard, with a moving average filter and simple peak detection with a threshold. It worked in controlled conditions but produced extremely inconsistent BPM readings whenever finger pressure shifted.

**Second Sensor** I switched to a MAX30101/MAX32664, a sensor with its own signal processing hub. This solved the reliability problem, but the hub's built-in BPM output doesn't show individual beat timing that HRV needs. I had to bypass the hub's processed output and read the raw infrared signal myself, then rebuild peak detection code from scratch.

**Several peak detection versions** My first peak detector on the new sensor caught alternated between two peaks on every pulse wave, which inflated HRV by measuring fake variation. I tried an upslope-based detector to fix this, but it made it a worse and missed about half of all real beats. I reverted to a running-max peak detector with a stricter fall-fraction threshold, which the current firmware uses.

**Signal filtering.** Early noise removal settings left too much noise in the signal and HRV stayed inflated even after peak detection improved. Tightening the smoothing constant made repeated readings have a consistent and stable range for the first time, which led to the breath hold experiment below.

## Key finding & hypothesis

Readings consistently came out higher than expected. I tested a hypothesis that it could be due to the natural rise and fall of heart rate with breathing (technically called sinus arrhythmia) instead of measurement errors.

I took a reading and held my breath partway through. RMSSD dropped from roughly 110ms during normal breathing to around 66ms during the breath hold. This confirms that a lot of the elevated value was real physiological variation due to breathing.

## Data analysis

I ran a linear regression testing whether the previous day's training load predicts next-morning HRV.

Days used: 17
Training load coefficient: -0.009 
R²: 0.005 

Training load explained under 1% of the variation in RMSSD, with essentially no relationship in this dataset. This suggests my recovery signal wasn't due to training load alone, and other factors (most likely sleep) may be affecting it.

## Known limitations

- The Arduino's polling rate is roughly 4.7ms per loop and sets a floor on how precisely beat timing can be measured, which limits the absolute accuracy of a reading. Day-to-day trends are more significant than a single reading.
- Using the regression requires a large and accurate dataset. You must have many days' worth of readings for it to work.

## Build it yourself

**Hardware:**
- Arduino Mega 2560
- SparkFun MAX30101/MAX32664 pulse oximeter and heart rate sensor
- Female-to-male jumper wires
- Small velcro strap or rubber band to secure finger
- Optional breadboard

**Wiring:**
- Sensor 3V3 → Arduino 3.3V
- Sensor GND → Arduino GND
- Sensor SDA → Arduino Pin 20
- Sensor SCL → Arduino Pin 21
- Sensor RST → Arduino Pin 4
- Sensor MFIO → Arduino Pin 5

**Software setup:**
1. Install the Arduino IDE and the SparkFun Bio Sensor Hub library
2. Upload `arduino/week3_hrv_v2/week3_hrv_v2.ino`
3. Install Python packages: `pip install pyserial pandas flask anthropic scikit-learn`
4. Get your own API key at [console.anthropic.com](https://console.anthropic.com). Usage cost for this project is a few cents total
5. Set the key: `$env:ANTHROPIC_API_KEY="your-key"` (Windows) or `export ANTHROPIC_API_KEY="your-key"` (Mac/Linux)
6. Run the logger each morning: `python python/logger.py`
7. View your dashboard: `python python/app.py`, then open `http://127.0.0.1:5000`

## Stack

- Arduino C++: sensor interfacing, signal processing, RMSSD calculation
- Python (pandas, scikit-learn, Flask): logging, analysis, dashboard
- Claude API: recovery interpretation
- GitHub: version control and documentation

## Built by

Lucas Runtz
