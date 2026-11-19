import http from "k6/http";
import { check } from "k6";

// The PNG is read once at init time and reused for every request.
const image = open("./sample.png", "b");

const SCENARIO = __ENV.RUN_SCENARIO || "calibration";

export const options = {
  scenarios: {
    [SCENARIO]: {
      executor: "constant-vus",
      // VUS concurrent closed-loop requests (one in flight per VU).
      vus: Number(__ENV.VUS || 1),
      duration: __ENV.DURATION || "60s",
      gracefulStop: "5s",
    },
  },
  // We intentionally do not fail the run on thresholds during calibration.
  thresholds: {},
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
    { timeout: "60s", tags: { step: __ENV.STEP || "cal" } },
  );

  check(res, {
    "status 200": (r) => r.status === 200,
    "has OCR output": (r) => (r.body || "").includes('"stdout"'),
    ...( __ENV.EXPECT
      ? { "expected text": (r) => (r.body || "").includes(__ENV.EXPECT) }
      : {}),
  });
}
