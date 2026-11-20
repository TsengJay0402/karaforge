import { en } from './en.ts'
import { errorText, formatBytes, translate, useI18n } from './index.ts'
import { zhTW } from './zh-TW.ts'

describe('i18n', () => {
  it('has the same keys and placeholders in both languages', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zhTW).sort())
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
    for (const key of Object.keys(zhTW) as (keyof typeof zhTW)[]) {
      expect([key, placeholders(en[key])]).toEqual([key, placeholders(zhTW[key])])
      expect(en[key].trim()).not.toBe('')
    }
  })

  it('fills in variables and leaves unknown ones alone', () => {
    expect(translate('zh-TW', 'list.lines', { lines: 3, tokens: 20 })).toBe('3 行 / 20 字')
    expect(translate('en', 'list.lines', { lines: 3, tokens: 20 })).toBe('3 lines / 20 tokens')
    expect(translate('en', 'list.lines', { lines: 3 })).toBe('3 lines / {tokens} tokens')
  })

  it('switches the language and remembers it', () => {
    useI18n.getState().setLang('en')
    expect(useI18n.getState().lang).toBe('en')
    expect(localStorage.getItem('karaforge.lang')).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    useI18n.getState().setLang('zh-TW')
    expect(document.documentElement.lang).toBe('zh-Hant')
  })

  it('picks the right side of a server error', () => {
    const error = {
      code: 'x',
      message_zh: '壞了',
      message_en: 'Broken',
      hint_zh: '再試一次',
      hint_en: null,
      detail: null,
    }
    expect(errorText('zh-TW', error)).toEqual({ message: '壞了', hint: '再試一次' })
    expect(errorText('en', error)).toEqual({ message: 'Broken', hint: null })
  })

  it('formats sizes', () => {
    expect([formatBytes(512), formatBytes(2048), formatBytes(5 << 20), formatBytes(1276 << 20)]).toEqual([
      '512 B',
      '2 KB',
      '5.0 MB',
      '1.2 GB',
    ])
  })
})
