# hrv-runner

HRV monitoring system for runners built with Arduino and Python.



## Status

Week 2 complete. Currently setting up new sensor & building logger with Python.

## What this is

A wearable device that measures heart rate variability every morning

to predict athletic recovery. Built from scratch using MAX30101 + MAX32664 pulse

sensor and Arduino Mega 2560.

## Hardware

- Arduino Mega 2560

- MAX30102 pulse oximeter and heart rate sensor (I2C communication)
- Jumper wires, breadboard

## Languages and tools

- Arduino C++ for sensor interfacing, signal processing, RMSSD/HRV calculation
- Python for data logging and dashboard (in progress)
- GitHub for version control and project documentation

## Languages and tools

- Arduino C++ for sensor interfacing, signal processing, RMSSD/HRV calculation

- Python for data logging and dashboard (in progress)

- GitHub for version control and project documentation



## Progress

- Week 1 - Sensor wired via I2C, raw R/IR/G data streaming to Serial Monitor.

- Week 2 - Signal processing complete. Moving average filter and BPM calculation verified against Garmin watch, but need better sensor for more consistent readings.

- Week 3 - RMSSD calculation for heart rate variability tracking implemented. MAX30101/MAX32664 Replacement sensor arrived. Setting up new configuration.

## Built by
Lucas Runtz
Summer 2026
