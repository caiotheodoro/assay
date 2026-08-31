/**
 * A sub-beat, with the crossfade built in.
 *
 * The cut used to be 26 hard cuts in under five minutes, one roughly every
 * eleven seconds, which is a large part of why it did not feel continuous. The
 * ground never cuts -- GridGround is identical in every scene -- so only the
 * content needs to move: outgoing fades and lifts, incoming rises into place,
 * and the two overlap.
 *
 * The curve is the site's own fadeUp, cubic-bezier(.25,.46,.45,.94), rather
 * than a transition library. Preset transitions are the templated look this
 * design has otherwise avoided, and they would be a dependency for something
 * that is twelve lines of interpolation.
 */
import React from "react";
import { AbsoluteFill, Easing, Sequence, interpolate, useCurrentFrame } from "remotion";

/**
 * Frames of handoff between neighbouring beats.
 *
 * A true crossfade was tried first and is wrong for this content: two dense
 * text panels at half opacity sit on top of each other and neither is legible.
 * These panels hand off instead -- the outgoing one clears over the first half
 * of the window, the grid ground shows through for a moment, and the incoming
 * one writes in over the second half. The ground never cuts, so it still reads
 * as one continuous surface rather than a cut.
 */
export const OVERLAP = 14;
/** Chapter changes get a longer breath. */
export const SCENE_OVERLAP = 20;

const FADE = Easing.bezier(0.25, 0.46, 0.45, 0.94);

export const Dissolve: React.FC<{
  durationInFrames?: number;
  overlap?: number;
  children: React.ReactNode;
}> = ({ durationInFrames, overlap = OVERLAP, children }) => {
  const frame = useCurrentFrame();

  // Incoming waits for the outgoing to have cleared: it rises over the second
  // half of the handoff window, not alongside it.
  const half = overlap / 2;
  const inOpacity = interpolate(frame, [half, overlap], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: FADE,
  });
  const outOpacity =
    durationInFrames === undefined
      ? 1
      : interpolate(
          frame,
          [durationInFrames - overlap, durationInFrames - half],
          [1, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: FADE },
        );

  const opacity = Math.min(inOpacity, outOpacity);
  // Rising in from below, lifting out above: the content moves through, it
  // does not sit still and blink.
  const y = (1 - inOpacity) * 10 - (1 - outOpacity) * 8;

  // AbsoluteFill, not a bare div: this element carries a transform, which makes
  // it the containing block for any AbsoluteFill inside it. A plain div gave the
  // panel no width and every title wrapped one word per line.
  return (
    <AbsoluteFill style={{ opacity, transform: `translateY(${y}px)` }}>{children}</AbsoluteFill>
  );
};

/**
 * `from` and `to` are the beat's own boundaries; the Sequence is extended past
 * `to` by the overlap so the crossfade has somewhere to live. Omit `to` for the
 * last beat of a scene -- the scene-level dissolve carries it out.
 */
export const Beat: React.FC<{
  from: number;
  to?: number;
  name: string;
  overlap?: number;
  children: React.ReactNode;
}> = ({ from, to, name, overlap = OVERLAP, children }) => {
  const duration = to === undefined ? undefined : to - from + overlap;
  return (
    <Sequence from={from} durationInFrames={duration} name={name} layout="none">
      <Dissolve durationInFrames={duration} overlap={overlap}>
        {children}
      </Dissolve>
    </Sequence>
  );
};
