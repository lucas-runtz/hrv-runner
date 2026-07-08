#include <SparkFun_Bio_Sensor_Hub_Library.h>
#include <Wire.h>

int resPin  = 4;
int mfioPin = 5;
SparkFun_Bio_Sensor_Hub bioHub(resPin, mfioPin);
bioData body;

const float BASELINE_ALPHA  = 0.01;
const float SMOOTH_BETA     = 0.15;
const float THRESH_FRACTION = 0.40;
const float PEAK_DECAY      = 0.99;
const float THRESH_FLOOR    = 15.0;
const float FALL_FRACTION   = 0.65;

const unsigned long REFRACTORY_MS = 500;
const unsigned long WARMUP_MS = 3000;
const float RR_MIN_MS = 300.0;
const float RR_MAX_MS = 1500.0;
const float RR_ARTIFACT_PCT = 0.20;
const int MEDIAN_WINDOW = 5;

const unsigned long SESSION_MS = 60000;
const int MIN_INTERVALS = 20;
const unsigned long FINGER_OFF_RESET_MS = 2000;

float smoothed = 0;
float baseline = 0;
bool filterPrimed = false;
unsigned long firstFingerTime = 0;

float signalPeak = 0;
uint32_t lastRawIr = 0;
unsigned long lastBeat = 0;
bool firstBeatSeen = false;

float runningMax = 0;
unsigned long runningMaxTime = 0;
bool beatLatched = false;

const int RR_CAP = 300;
float rr[RR_CAP];
int rrCount = 0;
unsigned long sessionStart = 0;
bool sessionStarted = false;
bool readingDone = false;

unsigned long fingerOffSince = 0;
bool fingerWasOff = false;

float recentRR[MEDIAN_WINDOW];
int recentRRCount = 0;
int recentRRIdx = 0;

float medianOfRecent() {
  float sorted[MEDIAN_WINDOW];
  int n = recentRRCount;
  for (int i = 0; i < n; i++) sorted[i] = recentRR[i];
  for (int i = 0; i < n - 1; i++)
    for (int j = 0; j < n - i - 1; j++)
      if (sorted[j] > sorted[j + 1]) {
        float t = sorted[j];
        sorted[j] = sorted[j + 1];
        sorted[j + 1] = t;
      }
  return sorted[n / 2];
}

void resetSession() {
  rrCount = 0;
  sessionStarted = false;
  readingDone = false;
  signalPeak = 0;
  recentRRCount = 0;
  recentRRIdx = 0;
  runningMax = 0;
  beatLatched = false;
  firstBeatSeen = false;
  filterPrimed = false;
  lastBeat = millis();
}

float calcRMSSD(float intervals[], int count) {
  if (count < 2) return 0;
  float sum = 0;
  for (int i = 0; i < count - 1; i++) {
    float diff = intervals[i + 1] - intervals[i];
    sum += diff * diff;
  }
  return sqrt(sum / (count - 1));
}

void hardResetHub() {
  pinMode(resPin, OUTPUT);
  pinMode(mfioPin, OUTPUT);
  digitalWrite(mfioPin, HIGH);
  digitalWrite(resPin, LOW);
  delay(20);
  digitalWrite(resPin, HIGH);
  delay(1000);
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  hardResetHub();

  int beginResult = bioHub.begin();
  if (beginResult != 0) {
    Serial.println("Hub not responding. Check wiring: 3V3, GND, SDA-20, SCL-21, RST-4, MFIO-5.");
  }
  delay(500);

  bioHub.configSensorBpm(MODE_ONE);
  delay(4000);

  Serial.println("Ready. Place finger with light, steady pressure. Hold still for 60s.");

  resetSession();
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r') resetSession();
  }

  body = bioHub.readSensorBpm();

  if (body.status != 3) {
    if (!fingerWasOff) {
      fingerOffSince = millis();
      fingerWasOff = true;
    }
    if (readingDone && millis() - fingerOffSince > FINGER_OFF_RESET_MS) {
      resetSession();
    }
    return;
  }
  fingerWasOff = false;

  if (readingDone) return;

  uint32_t ir = body.irLed;
  if (ir == lastRawIr) return;
  lastRawIr = ir;

  if (!filterPrimed) {
    smoothed = ir;
    baseline = ir;
    firstFingerTime = millis();
    filterPrimed = true;
    return;
  }

  smoothed += SMOOTH_BETA * (ir - smoothed);
  baseline += BASELINE_ALPHA * (ir - baseline);
  float ac = smoothed - baseline;

  if (ac > signalPeak) signalPeak = ac;
  else signalPeak *= PEAK_DECAY;
  float threshold = signalPeak * THRESH_FRACTION;
  if (threshold < THRESH_FLOOR) threshold = THRESH_FLOOR;

  if (ac > runningMax) {
    runningMax = ac;
    runningMaxTime = millis();
  }

  bool clearlyFalling = (runningMax - ac) > (runningMax * FALL_FRACTION);

  if (runningMax > threshold && clearlyFalling && !beatLatched) {
    unsigned long now = runningMaxTime;

    if (now - lastBeat > REFRACTORY_MS && millis() - firstFingerTime > WARMUP_MS) {
      if (!firstBeatSeen) {
        firstBeatSeen = true;
        lastBeat = now;
      } else {
        unsigned long interval = now - lastBeat;
        bool physiological = (interval >= RR_MIN_MS && interval <= RR_MAX_MS);
        bool consistent = true;
        if (recentRRCount >= 3) {
          float med = medianOfRecent();
          consistent = fabs((float)interval - med) <= RR_ARTIFACT_PCT * med;
        }

        if (physiological && consistent) {
          if (!sessionStarted) { sessionStart = now; sessionStarted = true; }
          if (rrCount < RR_CAP) rr[rrCount++] = interval;
          Serial.print("Beat ");
          Serial.print(rrCount);
          Serial.print("  RR: ");
          Serial.print(interval);
          Serial.print("ms  RMSSD: ");
          Serial.println(calcRMSSD(rr, rrCount), 1);
          recentRR[recentRRIdx] = interval;
          recentRRIdx = (recentRRIdx + 1) % MEDIAN_WINDOW;
          if (recentRRCount < MEDIAN_WINDOW) recentRRCount++;
        }
        lastBeat = now;
      }
    } else if (millis() - firstFingerTime > WARMUP_MS) {
      lastBeat = now;
    }
    beatLatched = true;
  }

  if (ac < threshold * 0.5) {
    beatLatched = false;
    runningMax = 0;
  }

  if (sessionStarted && rrCount >= MIN_INTERVALS &&
      millis() - sessionStart >= SESSION_MS) {
    float rmssd = calcRMSSD(rr, rrCount);
    Serial.print("RMSSD:");
    Serial.print(rmssd, 1);
    Serial.print(",beats:");
    Serial.print(rrCount);
    Serial.print(",bpm:");
    Serial.println(body.heartRate);
    readingDone = true;
  }
}