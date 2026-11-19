import http from "k6/http";
import { check, sleep } from "k6";

const image = open("./sample.png", "b");

// Peak concurrency was chosen in Stage 5: 10 concurrent requests already
// saturate this 2-vCPU node but stay below the 60s client timeout.
const PEAK = Number(__ENV.PEAK_VUS || 10);
const WARM = Number(__ENV.WARM_VUS || 1);

// k6 reserves the `scenario` tag for the executor name. Using the experiment
// name as the scenario key makes HTTP metrics carry scenario="B-hpa-50", etc.
const SCENARIO = __ENV.RUN_SCENARIO || "spike";

export const options = {
  scenarios: {
    [SCENARIO]: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "2m", target: WARM }, // warm-up
        { duration: "30s", target: PEAK }, // spike
        { duration: "3m", target: PEAK }, // hold at peak
        { duration: "30s", target: WARM }, // drop
        { duration: "4m", target: WARM }, // tail: observe scale-down
      ],
      gracefulRampDown: "30s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<5000"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export default function () {
  const res = http.post(
    `${__ENV.TARGET}/tesseract`,
    {
      file: http.file(image, "sample.png", "image/png"),
      options: JSON.stringify({
        languages: ["eng"],
        pageSegmentationMethod: 3,
      }),
    },
    { timeout: "60s" },
  );

  check(res, {
    "status 200": (r) => r.status === 200,
    "has OCR output": (r) => (r.body || "").includes('"stdout"'),
  });

  sleep(1);
}
