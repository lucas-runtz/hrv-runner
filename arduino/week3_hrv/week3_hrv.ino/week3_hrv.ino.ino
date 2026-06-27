#include <Wire.h>
#include "MAX30105.h" //SparkFun sensor library

MAX30105 particleSensor; //Declare variable for heart rate sensor (used MAX30102)
//establish variables for window size, readings from sensor, and index that tracks position in the ring buffer for rolling average of data
const int WINDOW = 10;
long readings[WINDOW] = {0};
int idx = 0;

//peak detection variables
long prevPrevSmoothed = 0; 
long prevSmoothed = 0;
unsigned long lastBeat = 0;
float bpm = 0;

//beat averaging variables
const int RR_COUNT = 4;
float rrIntervals[RR_COUNT] = {0};
int rrIdx = 0;
int beatCount = 0;

//hrv collection variables
const int HRV_BUFFER = 100;
float hrvIntervals[HRV_BUFFER] = {0};
int hrvCount = 0;
unsigned long sessionStart = 0;
bool sessionStarted = false;


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

float calcRMSSD(float intervals[], int count);

void setup() {
  //initialize Serial and particleSensor
  Serial.begin(115200);  //used 115200 baud rate for faster processing
  particleSensor.begin();
  particleSensor.setup();
}

void loop() {
  long smoothed = movingAvg(particleSensor.getIR());

  if (prevSmoothed > prevPrevSmoothed &&
      prevSmoothed > smoothed &&
      prevSmoothed > 109000) {  //only calculate if prevSmoothed is a peak and hits minimum amplitude of 109000

    unsigned long now = millis();

    if (now - lastBeat > 400) {  //400ms refractory period
      rrIntervals[rrIdx] = now - lastBeat;
      rrIdx = (rrIdx + 1) % RR_COUNT;

      if (hrvCount < HRV_BUFFER){
        hrvIntervals[hrvCount] = now - lastBeat;
        hrvCount++;
      }

      if (!sessionStarted){
        sessionStart = now;
        sessionStarted = true;
      }

      lastBeat = now;
      beatCount++;

      if (beatCount >= RR_COUNT) { //all 4 slots contain real data
        float avgRR = 0;

        for (int i = 0; i < RR_COUNT; i++) {
          avgRR += rrIntervals[i];
        }

        avgRR /= RR_COUNT;
        bpm = 60000.0 / avgRR;

        if (bpm > 35 && bpm < 150) {   //only realistic bpm readings
          Serial.print("BPM: ");
          Serial.println(bpm);
        }
      }
    }
  }

//advance smoothed readings
  prevPrevSmoothed = prevSmoothed; 
  prevSmoothed = smoothed;

  if (hrvCount >= 30 && millis() - sessionStart >= 60000) {
    float rmssd = calcRMSSD(hrvIntervals, hrvCount);
    Serial.print("RMSSD: ");
    Serial.println(rmssd);
  }
  delay(10);   
}

float calcRMSSD(float intervals[], int count){
  float sum = 0;

  for (int i = 0; i < count - 1; i++){
    float difference = intervals[i] - intervals[i + 1];
    sum += (difference * difference);
  }

  float average = sum / (count - 1);
  return sqrt(average);
}

