import type { MessageKey } from '../i18n/index.ts'

/** The shortcuts shown in the help panel (the handling itself lives in `Editor.tsx`). */
export const HOTKEYS: { keys: string[]; description: MessageKey }[] = [
  { keys: ['Space'], description: 'help.space' },
  { keys: ['←', '→'], description: 'help.arrows' },
  { keys: ['Alt', '←/→'], description: 'help.altArrows' },
  { keys: ['Tab', 'Shift+Tab'], description: 'help.tab' },
  { keys: ['Home'], description: 'help.home' },
  { keys: ['[', ']'], description: 'help.seek' },
  { keys: ['Ctrl+Z', 'Ctrl+Shift+Z'], description: 'help.undo' },
  { keys: ['L'], description: 'help.lock' },
  { keys: ['Delete'], description: 'help.delete' },
  { keys: ['+', '−'], description: 'help.zoom' },
  { keys: ['1', '2'], description: 'help.tapModes' },
  { keys: ['Ctrl+S'], description: 'help.save' },
  { keys: ['Esc'], description: 'help.escape' },
  { keys: ['?'], description: 'help.help' },
]

/** What the mouse does on the timeline (also shown in the help panel). */
export const MOUSE_ACTIONS: { action: MessageKey; description: MessageKey }[] = [
  { action: 'help.mouse.box', description: 'help.mouse.boxHint' },
  { action: 'help.mouse.group', description: 'help.mouse.groupHint' },
  { action: 'help.mouse.edge', description: 'help.mouse.edgeHint' },
]

/** Whether a key event comes from a field the user is typing into. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}
