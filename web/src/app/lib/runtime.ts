// How this copy of the app is running.
//   standalone: one self-contained HTML file (opened from disk, or hosted as a single page).
//               No server is assumed: image recognition and AI explain stay off.
//   server:     built and served by Vite or nginx next to the LogicLens API.

export const STANDALONE: boolean =
  import.meta.env.VITE_STANDALONE === "1" || (typeof location !== "undefined" && location.protocol === "file:");
