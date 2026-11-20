import { create } from 'zustand'

import type { ApiErrorBody } from '../api/types.ts'
import { en } from './en.ts'
import { type MessageKey, zhTW } from './zh-TW.ts'

export type Lang = 'zh-TW' | 'en'
export type { MessageKey } from './zh-TW.ts'

const STORAGE_KEY = 'karaforge.lang'
const dictionaries: Record<Lang, Record<MessageKey, string>> = { 'zh-TW': zhTW, en }

export type Vars = Record<string, string | number>

export function translate(lang: Lang, key: MessageKey, vars?: Vars): string {
  const template = dictionaries[lang][key]
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}

function initialLang(): Lang {
  try {
    const stored = globalThis.localStorage.getItem(STORAGE_KEY)
    if (stored === 'zh-TW' || stored === 'en') return stored
  } catch {
    // Storage may be unavailable (private mode); fall through to the browser language.
  }
  const browser = globalThis.navigator.language.toLowerCase()
  return browser.startsWith('zh') ? 'zh-TW' : browser.startsWith('en') ? 'en' : 'zh-TW'
}

interface I18nState {
  lang: Lang
  setLang: (lang: Lang) => void
}

export const useI18n = create<I18nState>((set) => ({
  lang: initialLang(),
  setLang: (lang) => {
    try {
      globalThis.localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      // Not being able to remember the choice is not worth an error.
    }
    globalThis.document.documentElement.lang = lang === 'zh-TW' ? 'zh-Hant' : 'en'
    set({ lang })
  },
}))

export type Translate = (key: MessageKey, vars?: Vars) => string

/** The translation function for the current language (re-renders when it changes). */
export function useT(): Translate {
  const lang = useI18n((state) => state.lang)
  return (key, vars) => translate(lang, key, vars)
}

/** Message and hint of a server error in the given language. */
export function errorText(lang: Lang, error: ApiErrorBody): { message: string; hint: string | null } {
  return lang === 'zh-TW'
    ? { message: error.message_zh, hint: error.hint_zh }
    : { message: error.message_en, hint: error.hint_en }
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1 << 30) return `${(bytes / (1 << 30)).toFixed(1)} GB`
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(bytes >= 100 << 20 ? 0 : 1)} MB`
  if (bytes >= 1 << 10) return `${Math.round(bytes / (1 << 10))} KB`
  return `${bytes} B`
}
