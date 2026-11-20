import { createContext, useContext } from 'react'
import { useStore } from 'zustand'

import type { AnalysisData, MediaName } from '../api/types.ts'
import type { EditorState, EditorStore } from './store.ts'
import type { Transport } from './transport.ts'

export interface EditorContextValue {
  id: string
  store: EditorStore
  transport: Transport
  media: Record<MediaName, string | null>
  analysis: AnalysisData
}

export const EditorContext = createContext<EditorContextValue | null>(null)

export function useEditor(): EditorContextValue {
  const value = useContext(EditorContext)
  if (!value) throw new Error('useEditor must be used inside the editor')
  return value
}

/** Subscribe to a slice of the editor state. */
export function useEditorState<T>(selector: (state: EditorState) => T): T {
  return useStore(useEditor().store, selector)
}

export const useDoc = () => useEditorState((state) => state.history.present)
