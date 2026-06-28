# hrv-runner

Heart rate variability monitoring system for runners built with Arduino and Python. 

## Status

Week 2 complete. Currently awaiting sensor to ship & building logger with Python.

## What this is

A wearable device that measures heart rate variability every morning
to predict athletic recovery. Built from scratch using a MAX30101 + MAX32664 pulse
sensor and Arduino Mega 2560 with Python data logging.

## Hardware

Arduino Mega 2560
MAX30102 pulse oximeter and heart rate sensor (I2C communication)
Jumper wires, breadboard

## Languages and tools

Arduino C++ for sensor interfacing, signal processing, RMSSD/HRV calculation
Python for data logging and dashboard (in progress)
GitHub for version control and project documentation

## Progress

Week 1 - Sensor wired via I2C, raw R/IR/G data streaming to Serial Monitor.
Week 2 - Signal processing complete. Moving average filter and BPM calculation verified against Garmin watch, but need better sensor for more consistent readings.
Week 3 - RMSSD calculation for heart rate variability tracking implemented. Waiting for replacement sensor for validation. Building data logger with Python.

## Built by
Lucas Runtz
Summer 2026
