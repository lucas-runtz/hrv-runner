# hrv-runner

HRV monitoring system for runners built with Arduino and Python.


## Status

Week 4 and 5 complete. HRV detection with new sensor working, Python logger to CSV file finished, and Claude API can inference recovery status from CSV data. Currently working on logging daily readings for sufficient data and 

expanding features.


## What this is

A wearable device that measures heart rate variability every morning

to predict athletic recovery. Built from scratch using MAX30101 + MAX32664 pulse

sensor and Arduino Mega 2560.


## Hardware

- Arduino Mega 2560

- MAX30101 & MAX 32664 pulse oximeter and heart rate sensor (I2C communication)

- Jumper wires, breadboard


## Languages and tools

- Arduino C++ for sensor interfacing, signal processing, RMSSD/HRV calculation

- Python for data logging and dashboard, plus sending data to Claude API for inference

- GitHub for version control and project documentation


## Progress

- Week 1 - Sensor wired via I2C, raw R/IR/G data streaming to Serial Monitor.

- Week 2 - Signal processing complete. Moving average filter and BPM calculation verified against Garmin watch, but need better sensor for more consistent readings.

- Week 3 - RMSSD calculation for heart rate variability tracking implemented. MAX30101/MAX32664 Replacement sensor arrived. Setting up new configuration.

- Week 4 - MAX30101 & MAX32664 (dual sensor) circuit set up. Heartbeat and RMSSD/HRV detection with new configuration works.

- Week 5 - Python CSV logger with training load done. Graph visualization dashboard finished and turned into Flask app. AI recovery assessment with Claude API working.


## Built by

Lucas Runtz
Summer 2026
