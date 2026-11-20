import { type MediaLike, Transport } from './transport.ts'

class FakeMedia implements MediaLike {
  currentTime = 0
  playbackRate = 1
  muted = false
  paused = true
  duration = 60
  plays = 0
  private ended: (() => void)[] = []

  play(): Promise<void> {
    this.paused = false
    this.plays += 1
    return Promise.resolve()
  }

  pause(): void {
    this.paused = true
  }

  addEventListener(type: 'ended' | 'error', listener: () => void): void {
    if (type === 'ended') this.ended.push(listener)
  }

  finish(): void {
    this.paused = true
    this.ended.forEach((listener) => listener())
  }
}

function setup(sources: Record<string, string> = { instrumental: 'i.wav', original: 'o.wav', vocals: 'v.wav' }) {
  const created: Record<string, FakeMedia> = {}
  const frames: (() => void)[] = []
  const transport = new Transport({
    sources,
    durationMs: 60_000,
    createAudio: (url) => (created[url] = new FakeMedia()),
    requestFrame: (callback) => frames.push(callback),
    cancelFrame: () => undefined,
  })
  const tick = () => frames.shift()?.()
  return { transport, created, tick, frames }
}

describe('transport', () => {
  it('plays the selected mix and reports time to its listeners', async () => {
    const { transport, created, tick } = setup()
    const seen: [number, boolean][] = []
    transport.subscribe((time, playing) => seen.push([time, playing]))
    expect(transport.modes).toEqual(['instrumental', 'original', 'vocals'])
    expect([transport.mode, transport.playing, transport.now()]).toEqual(['instrumental', false, 0])
    expect(created).toEqual({}) // no audio element exists before it is needed

    await transport.play()
    expect(created['i.wav']?.paused).toBe(false)
    created['i.wav']!.currentTime = 1.25
    tick()
    expect(seen.at(-1)).toEqual([1250, true])
    transport.pause()
    expect(seen.at(-1)).toEqual([1250, false])
    expect(transport.playing).toBe(false)
  })

  it('keeps the position when the mix changes', async () => {
    const { transport, created } = setup()
    transport.seek(12_500)
    await transport.play()
    await transport.setMode('vocals')
    expect(transport.mode).toBe('vocals')
    expect(created['v.wav']).toMatchObject({ currentTime: 12.5, paused: false })
    expect(created['i.wav']?.paused).toBe(true)
    await transport.setMode('vocals')
    expect(created['v.wav']?.plays).toBe(1)
  })

  it('falls back to the mixes that exist', async () => {
    const { transport, created } = setup({ original: 'o.wav' })
    expect([transport.modes, transport.mode]).toEqual([['original'], 'original'])
    await transport.setMode('instrumental')
    expect(transport.mode).toBe('original')
    await transport.toggle()
    expect(created['o.wav']?.paused).toBe(false)
    await transport.toggle()
    expect(created['o.wav']?.paused).toBe(true)
  })

  it('clamps seeking and the playback rate', () => {
    const { transport, created } = setup()
    transport.seek(-500)
    expect(transport.now()).toBe(0)
    transport.seek(99_000)
    expect(transport.now()).toBe(60_000)
    transport.setRate(3)
    expect([transport.rate, created['i.wav']?.playbackRate]).toEqual([1.5, 1.5])
    transport.setRate(0.1)
    expect(transport.rate).toBe(0.5)
  })

  it('keeps a muted video element in step', async () => {
    const { transport, created, tick } = setup()
    const video = new FakeMedia()
    transport.seek(5000)
    transport.attachVideo(video)
    expect([video.muted, video.currentTime]).toEqual([true, 5])
    await transport.play()
    expect(video.paused).toBe(false)
    created['i.wav']!.currentTime = 5.05
    video.currentTime = 5.04
    tick()
    expect(video.currentTime).toBe(5.04) // within tolerance: left alone
    created['i.wav']!.currentTime = 6
    tick()
    expect(video.currentTime).toBe(6)
    transport.pause()
    expect(video.paused).toBe(true)
  })

  it('restarts from the beginning after the end and stops when the audio ends', async () => {
    const { transport, created } = setup()
    const states: boolean[] = []
    transport.subscribe((_time, playing) => states.push(playing))
    transport.seek(60_000)
    await transport.play()
    expect(created['i.wav']?.currentTime).toBe(0)
    created['i.wav']?.finish()
    expect(states.at(-1)).toBe(false)
    transport.stop()
  })

  it('works without any audio at all', async () => {
    const { transport } = setup({})
    transport.seek(3000)
    expect(transport.now()).toBe(3000)
    await transport.play()
    expect(transport.playing).toBe(false)
  })
})
