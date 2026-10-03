<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { BarChart3, FileText, LogOut, Menu, Moon, Sun, Wand2 } from 'lucide-vue-next'

import ChatMessage from '@/components/chat/ChatMessage.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import SkillBar from '@/components/chat/SkillBar.vue'
import Sidebar from '@/components/layout/Sidebar.vue'
import Button from '@/components/ui/Button.vue'
import { useTheme } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()
const { isDark, toggleDark } = useTheme()

const scrollRef = ref<HTMLElement>()
const sidebarOpen = ref(false)
const inputRef = ref()

const currentTitle = computed(
  () => chat.sessions.find((s) => s.id === chat.currentSessionId)?.title ?? '',
)

watch(
  () => chat.messages.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)

function onSelect(id: string) {
  chat.selectSession(id)
  sidebarOpen.value = false
}

function onSkillSelect(trigger: string) {
  inputRef.value?.insertText(trigger + '：')
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <!-- 移动端遮罩 -->
    <div
      v-if="sidebarOpen"
      class="absolute inset-0 z-20 bg-black/40 lg:hidden"
      @click="sidebarOpen = false"
    />
    <!-- 侧栏: 移动端抽屉 / 桌面静态 -->
    <div
      :class="[
        'absolute z-30 h-full transition-transform duration-200 lg:static lg:translate-x-0',
        sidebarOpen ? 'translate-x-0' : '-translate-x-full',
      ]"
    >
      <Sidebar
        :sessions="chat.sessions"
        :current-id="chat.currentSessionId"
        @create="chat.newSession"
        @select="onSelect"
        @remove="chat.deleteSession"
      />
    </div>

    <div class="flex flex-1 flex-col">
      <header class="flex items-center gap-3 border-b border-border bg-card px-4 py-3">
        <Button
          variant="ghost"
          size="icon"
          class="lg:hidden"
          title="菜单"
          @click="sidebarOpen = !sidebarOpen"
        >
          <Menu class="h-4 w-4" />
        </Button>
        <span class="flex-1 truncate font-medium">{{ currentTitle || 'Agent-Harness' }}</span>

        <span
          v-if="chat.streaming"
          class="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex"
        >
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          正在生成…
        </span>

        <div class="flex rounded-md border border-border p-0.5">
          <button
            type="button"
            :class="[
              'rounded px-3 py-1 text-sm transition-colors',
              chat.mode === 'chat'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            ]"
            @click="chat.mode = 'chat'"
          >
            对话
          </button>
          <button
            type="button"
            :class="[
              'rounded px-3 py-1 text-sm transition-colors',
              chat.mode === 'document'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            ]"
            @click="chat.mode = 'document'"
          >
            文档生成
          </button>
        </div>

        <Button
          variant="ghost"
          size="icon"
          :title="isDark ? '切换到浅色' : '切换到暗色'"
          @click="toggleDark()"
        >
          <Sun v-if="isDark" class="h-4 w-4" />
          <Moon v-else class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" title="技能管理" @click="router.push('/skills')">
          <Wand2 class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" title="文档管理" @click="router.push('/documents')">
          <FileText class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" title="评估中心" @click="router.push('/evaluation')">
          <BarChart3 class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" title="退出登录" @click="logout">
          <LogOut class="h-4 w-4" />
        </Button>
      </header>

      <div ref="scrollRef" class="flex-1 overflow-y-auto p-4">
        <div
          v-if="!chat.messages.length"
          class="flex h-full flex-col items-center justify-center text-muted-foreground"
        >
          <p v-if="chat.loadingMessages" class="text-lg">正在加载历史消息…</p>
          <template v-else>
            <p class="text-lg">开始对话吧</p>
            <p class="mt-1 text-sm">
              {{
                chat.mode === 'document'
                  ? '输入主题，Writer 将生成结构化 Markdown 文档'
                  : '支持多模态：上传图片提问，或直接聊天'
              }}
            </p>
          </template>
        </div>
        <div v-else class="space-y-4">
          <ChatMessage
            v-for="m in chat.messages"
            :key="m.id"
            :message="m"
            @retry="chat.retryLast"
          />
        </div>
      </div>

      <SkillBar @select="onSkillSelect" />
      <MessageInput
        ref="inputRef"
        :mode="chat.mode"
        :streaming="chat.streaming"
        @send="chat.send"
      />
    </div>
  </div>
</template>
