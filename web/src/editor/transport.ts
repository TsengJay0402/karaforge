/**
 * The playback clock of the editor.
 *
 * One audio element per available mix (karaoke / original / vocals only) is kept ready; the
 * one that is selected plays and is the master clock.  The video element, the subtitle
 * renderer and the timeline all follow `now()`, so switching the mix never loses the place.
 */
import type { AudioMode } from './store.ts'

/** The part of `HTMLMediaElement` the transport uses (so that tests can substitute it). */
export interface MediaLike {
  currentTime: number
  playbackRate: number
  muted: boolean
  readonly paused: boolean
  readonly duration: number
  play: () => Promise<void>
  pause: () => void
  addEventListener: (type: 'ended' | 'error', listener: () => void) => void
}

export type Listener = (timeMs: number, playing: boolean) => void

export interface TransportOptions {
  sources: Partial<Record<AudioMode, string>>
  createAudio: (url: string) => MediaLike
  requestFrame?: (callback: () => void) => number
  cancelFrame?: (handle: number) => void
  durationMs: number
}

const MODES: AudioMode[] = ['instrumental', 'original', 'vocals']
const VIDEO_DRIFT_S = 0.12

export class Transport {
  private readonly audios: Partial<Record<AudioMode, MediaLike>> = {}
  private readonly listeners = new Set<Listener>()
  private readonly requestFrame: (callback: () => void) => number
  private readonly cancelFrame: (handle: number) => void
  private video: MediaLike | null = null
  private frame: number | null = null
  private current: AudioMode
  private speed = 1
  private position = 0
  readonly durationMs: number

  constructor(options: TransportOptions) {
    this.durationMs = options.durationMs
    this.requestFrame = options.requestFrame ?? ((callback) => globalThis.requestAnimationFrame(callback))
    this.cancelFrame = options.cancelFrame ?? ((handle) => globalThis.cancelAnimationFrame(handle))
    for (const mode of MODES) {
      const url = options.sources[mode]
      if (!url) continue
      const audio = options.createAudio(url)
      audio.addEventListener('ended', () => {
        if (this.mode === mode) this.stopLoop()
      })
      this.audios[mode] = audio
    }
    this.current = MODES.find((mode) => this.audios[mode]) ?? 'original'
  }

  /** Mixes that can be selected for this project. */
  get modes(): AudioMode[] {
    return MODES.filter((mode) => this.audios[mode])
  }

  get mode(): AudioMode {
    return this.current
  }

  get rate(): number {
    return this.speed
  }

  private get master(): MediaLike | undefined {
    return this.audios[this.current]
  }

  get playing(): boolean {
    const master = this.master
    return master !== undefined && !master.paused
  }

  /** Current position in milliseconds. */
  now(): number {
    const master = this.master
    return master ? master.currentTime * 1000 : this.position
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private emit(): void {
    const time = this.now()
    const playing = this.playing
    for (const listener of this.listeners) listener(time, playing)
  }

  private syncVideo(force: boolean): void {
    const video = this.video
    if (!video) return
    const target = this.now() / 1000
    if (force || Math.abs(video.currentTime - target) > VIDEO_DRIFT_S) video.currentTime = target
    video.playbackRate = this.speed
    if (this.playing && video.paused) void video.play().catch(() => undefined)
    if (!this.playing && !video.paused) video.pause()
  }

  private loop = (): void => {
    this.frame = null
    this.syncVideo(false)
    this.emit()
    if (this.playing) this.frame = this.requestFrame(this.loop)
  }

  private stopLoop(): void {
    if (this.frame !== null) this.cancelFrame(this.frame)
    this.frame = null
    this.syncVideo(false)
    this.emit()
  }

  /** The (muted) video element that shows the picture, if the project has one. */
  attachVideo(video: MediaLike | null): void {
    this.video = video
    if (video) {
      video.muted = true
      this.syncVideo(true)
    }
  }

  async play(): Promise<void> {
    const master = this.master
    if (!master) return
    if (this.durationMs > 0 && this.now() >= this.durationMs - 50) master.currentTime = 0
    master.playbackRate = this.speed
    await master.play()
    if (this.frame === null) this.frame = this.requestFrame(this.loop)
    this.syncVideo(true)
    this.emit()
  }

  pause(): void {
    this.master?.pause()
    this.stopLoop()
  }

  async toggle(): Promise<void> {
    if (this.playing) this.pause()
    else await this.play()
  }

  seek(timeMs: number): void {
    const limit = this.durationMs > 0 ? this.durationMs : Number.POSITIVE_INFINITY
    const clamped = Math.min(Math.max(0, timeMs), limit)
    this.position = clamped
    const master = this.master
    if (master) master.currentTime = clamped / 1000
    this.syncVideo(true)
    this.emit()
  }

  async setMode(mode: AudioMode): Promise<void> {
    const next = this.audios[mode]
    if (!next || mode === this.current) return
    const wasPlaying = this.playing
    const time = this.now()
    this.master?.pause()
    this.current = mode
    next.currentTime = time / 1000
    next.playbackRate = this.speed
    if (wasPlaying) await next.play()
    this.emit()
  }

  setRate(rate: number): void {
    this.speed = Math.min(1.5, Math.max(0.5, rate))
    const master = this.master
    if (master) master.playbackRate = this.speed
    this.syncVideo(false)
  }

  destroy(): void {
    if (this.frame !== null) this.cancelFrame(this.frame)
    this.frame = null
    for (const mode of MODES) this.audios[mode]?.pause()
    this.video?.pause()
    this.listeners.clear()
  }
}
