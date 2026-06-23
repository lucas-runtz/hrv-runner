#include <Wire.h>
#include "MAX30105.h" //SparkFun sensor library

MAX30105 particleSensor; //Declare variable for heart rate sensor (used MAX30102)
//establish variables for window size, readings from senor, and index that tracks position in the ring buffer for rolling average of data
const int WINDOW = 10;
long readings[WINDOW] = {0};
int idx = 0;

//for calculating heartbeats
unsigned long prevPrevSmoothed = 0;
unsigned long prevSmoothed = 0;
unsigned long lastBeat = 0;
float bpm = 0;

const int RR_COUNT = 4;
float rrIntervals[RR_COUNT] = {0};
int rrIdx = 0;


//function calculates moving average with values in readings
long movingAvg(long newVal){

  long sum = 0;
  readings[idx] = newVal;  //stores newest sensor reading into current slot of ring buffer, overwrites previous value
  idx = (idx + 1) % WINDOW; //advances index, wraps back to zero when it reaches 10, creating circular behavior

  for (int i = 0; i < WINDOW; i++){ 
    sum += readings[i];  //sum values in readings by iterating through all 10 slots
  }

  return sum / WINDOW;  //return average
}

void setup() {

  //initialize Serial and particleSensor
  Serial.begin(115200);  //used 115200 baud rate for faster processing
  particleSensor.begin();
  particleSensor.setup();
}

void loop() {

  long smoothed = movingAvg(particleSensor.getIR());

  // peak detection
  if (prevSmoothed > prevPrevSmoothed && prevSmoothed > smoothed && prevSmoothed > 109000){  // 
unsigned long now = millis();
if (now - lastBeat > 400) {
    rrIntervals[rrIdx] = now - lastBeat;
    rrIdx = (rrIdx + 1) % RR_COUNT;
    lastBeat = now;
    
    float avgRR = 0;
    for (int i = 0; i < RR_COUNT; i++) {
        avgRR += rrIntervals[i];
    }
    avgRR /= RR_COUNT;
    
    if (avgRR > 0) {
        bpm = 60000.0 / avgRR;
        if (bpm > 35 && bpm < 150) {
            Serial.print("BPM: ");
            Serial.println(bpm);
        }
    }
}
    
   
  }

  //Serial.print("S: ");
//Serial.println(smoothe

  prevPrevSmoothed = prevSmoothed;
  prevSmoothed = smoothed;

  
  delay(10); //prevents Serial from being overwhelmed with data
}
