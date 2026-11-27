// In the existing service container this is a same-origin relative endpoint.
// A standalone preview can process images locally with the bundled English model.
export const ocrEndpoint = import.meta.env.VITE_OCR_ENDPOINT?.trim()
async function serviceRecognition(image: Blob | string): Promise<string> {
  const blob = typeof image === "string" ? await (await fetch(image)).blob() : image
  const form = new FormData()
  form.append("file", blob, blob.type === "image/png" ? "page.png" : "page.jpg")
  form.append("options", JSON.stringify({languages: ["eng"], pageSegmentationMethod: 3}))
  const response = await fetch(ocrEndpoint, { method: "POST", body: form, signal: AbortSignal.timeout(120000) })
  if (!response.ok) throw new Error("The OCR service could not process the image.")
  const { data } = await response.json()
  if (data?.exit?.code !== 0 || typeof data?.stdout !== "string") throw new Error("The OCR service returned an invalid result.")
  return data.stdout.trim()
}
export async function recognize(image: Blob | string): Promise<string> {
  if (ocrEndpoint) return serviceRecognition(image)
  const { createWorker, OEM } = await import("tesseract.js")
  const base = new URL("/ocr/", window.location.origin).href
  const worker = await createWorker("eng", OEM.LSTM_ONLY, {
    workerPath: base + "worker.min.js", corePath: base, langPath: base, workerBlobURL: false,
  })
  try {
    const { data } = await worker.recognize(image)
    return data.text.trim()
  } finally { await worker.terminate() }
}
