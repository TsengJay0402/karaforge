import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'

import { connectEvents } from './api/events.ts'
import { type Lang, useI18n, useT } from './i18n/index.ts'
import { NewProject } from './pages/NewProject.tsx'
import { ProjectList } from './pages/ProjectList.tsx'
import { ProjectPage } from './pages/ProjectPage.tsx'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

export function LanguageSwitch() {
  const { lang, setLang } = useI18n()
  const t = useT()
  return (
    <label className="language-switch">
      <span className="visually-hidden">{t('app.language')}</span>
      <select
        value={lang}
        aria-label={t('app.language')}
        onChange={(event) => setLang(event.target.value as Lang)}
      >
        <option value="zh-TW">繁體中文</option>
        <option value="en">English</option>
      </select>
    </label>
  )
}

export function Shell() {
  const t = useT()
  useEffect(() => connectEvents(), [])
  return (
    <div className="app">
      <Routes>
        <Route
          path="/p/:id"
          element={<ProjectPage />}
        />
        <Route
          path="*"
          element={
            <>
              <header className="app-header">
                <Link to="/" className="brand">
                  <span className="brand-mark">K</span>
                  <span>
                    <strong>KaraForge</strong>
                    <small>{t('app.tagline')}</small>
                  </span>
                </Link>
                <LanguageSwitch />
              </header>
              <main className="app-main">
                <Routes>
                  <Route path="/" element={<ProjectList />} />
                  <Route path="/new" element={<NewProject />} />
                  <Route path="*" element={<ProjectList />} />
                </Routes>
              </main>
            </>
          }
        />
      </Routes>
    </div>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
