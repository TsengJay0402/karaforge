/**
 * Stands in for the `rvfc-polyfill` package, which JASSUB imports for its side effect.
 *
 * That package is licensed GPL-3.0, so it must not end up in the bundle KaraForge
 * distributes (Apache-2.0).  It adds `HTMLVideoElement.requestVideoFrameCallback` to browsers
 * that lack it, and JASSUB only calls that method when it is given a `<video>` to follow.
 * KaraForge runs JASSUB in canvas mode and tells it the time of every frame itself
 * (see `editor/Preview.tsx`), so nothing here needs the method and an empty module is enough.
 *
 * `vite.config.ts` points the import at this file and fails the build if the original code
 * shows up in the output anyway.
 */
export {}
