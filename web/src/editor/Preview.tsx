/**
 * The preview: picture (source video or the theme's background), with the lyrics rendered by
 * JASSUB — libass compiled to WebAssembly — from the very ASS script an export burns in.
 *
 * JASSUB is used in "canvas" mode and told the time of every frame, so the preview follows
 * the editor's own clock (the selected audio mix), not a video element.
 */
import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client.ts'
import type { ApiErrorBody, FontEntry } from '../api/types.ts'
import { ErrorBox, toErrorBody } from '../components/common.tsx'
import { useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'

const PREVIEW_DELAY_MS = 250

interface Renderer {
  setTrack: (ass: string) => void
  render: (timeMs: number, repaint: boolean) => void
  destroy: () => void
}

async function createRenderer(
  canvas: HTMLCanvasElement,
  ass: string,
  fonts: FontEntry[],
  size: [number, number],
): Promise<Renderer> {
  const { default: JASSUB } = await import('jassub')
  const available: Record<string, string> = {}
  for (const font of fonts) available[font.family.toLowerCase()] = font.url
  const instance = new JASSUB({
    canvas,
    subContent: ass,
    availableFonts: available,
    defaultFont: fonts[0]?.family.toLowerCase(),
    queryFonts: false,
  })
  await instance.ready
  return {
    setTrack: (content) => void instance.renderer.setTrack(content),
    render: (timeMs, repaint) =>
      void instance.manualRender(
        {
          expectedDisplayTime: performance.now(),
          width: size[0],
          height: size[1],
          mediaTime: timeMs / 1000,
        },
        repaint,
      ),
    destroy: () => void instance.destroy(),
  }
}

export function Preview() {
  const t = useT()
  const { id, store, transport, media } = useEditor()
  const doc = useEditorState((state) => state.history.present)
  const canvas = useRef<HTMLCanvasElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const renderer = useRef<Renderer | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'empty'>('loading')
  const [failure, setFailure] = useState<ApiErrorBody | null>(null)
  const [width, height] = doc.render.resolution
  const hasVideo = doc.media.has_video && media.source !== null
  const hasTiming = doc.lines.some((line) => line.tokens.some((token) => token.start_ms !== null))

  // The picture follows the transport.
  useEffect(() => {
    const element = video.current
    transport.attachVideo(element)
    return () => transport.attachVideo(null)
  }, [transport, hasVideo])

  // Lyrics are drawn for every tick of the transport.
  useEffect(
    () => transport.subscribe((time) => renderer.current?.render(time, false)),
    [transport],
  )

  // Re-render the script shortly after the document changes.
  useEffect(() => {
    if (!hasTiming) {
      setStatus('empty')
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const result = await api.preview(id, store.getState().history.present)
          if (cancelled) return
          const target = canvas.current
          if (!target) return
          if (renderer.current) {
            renderer.current.setTrack(result.ass)
          } else {
            const fonts = await api.fonts()
            if (cancelled) return
            // Fonts the script uses first: the first one doubles as the fallback.
            const used = new Set(result.fonts.map((font) => font.file))
            const ordered = [...result.fonts, ...fonts.filter((font) => !used.has(font.file))]
            const created = await createRenderer(target, result.ass, ordered, [result.width, result.height])
            if (cancelled) {
              created.destroy()
              return
            }
            renderer.current = created
          }
          setFailure(null)
          setStatus('ready')
          renderer.current.render(transport.now(), true)
        } catch (cause) {
          if (!cancelled) setFailure(toErrorBody(cause))
        }
      })()
    }, PREVIEW_DELAY_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [doc, hasTiming, id, store, transport])

  useEffect(
    () => () => {
      renderer.current?.destroy()
      renderer.current = null
    },
    [],
  )

  return (
    <section className="preview" aria-label="preview">
      <div
        className="preview-stage"
        data-testid="preview-stage"
        style={{ aspectRatio: `${width} / ${height}` }}
        onClick={() => void transport.toggle()}
      >
        {hasVideo && media.source ? (
          <video ref={video} src={media.source} muted playsInline preload="auto" />
        ) : (
          <div className="preview-backdrop" />
        )}
        <canvas ref={canvas} data-testid="preview-canvas" data-status={status} />
        {status === 'loading' && !failure ? <p className="preview-note">{t('editor.preview.loading')}</p> : null}
        {status === 'empty' ? <p className="preview-note">{t('editor.noTiming')}</p> : null}
      </div>
      {failure ? (
        <ErrorBox error={failure}>
          <small>{t('editor.preview.failed')}</small>
        </ErrorBox>
      ) : null}
    </section>
  )
}
