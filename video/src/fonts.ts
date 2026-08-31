/**
 * Only the weights and subsets the video uses. Loading the full families made
 * ~250 network requests per render, which Remotion warns about and which slows
 * every frame of a 8100-frame render.
 */
import { loadFont as loadMono } from "@remotion/google-fonts/GeistMono";
import { loadFont as loadSans } from "@remotion/google-fonts/PlusJakartaSans";

export const { fontFamily: sansFamily } = loadSans("normal", {
  weights: ["400", "600", "700"],
  subsets: ["latin"],
});

export const { fontFamily: monoFamily } = loadMono("normal", {
  weights: ["400", "600"],
  subsets: ["latin"],
});
