import { useDark, useToggle } from '@vueuse/core'

// 模块级单例: 全局共享同一暗色状态, 切换 html 上的 .dark class 并持久化到 localStorage
export const isDark = useDark()
export const toggleDark = useToggle(isDark)

export function useTheme() {
  return { isDark, toggleDark }
}
