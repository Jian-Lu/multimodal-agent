<script setup lang="ts">
import { RouterView } from 'vue-router'

import Toast from '@/components/Toast.vue'
import { useTheme } from '@/composables/useTheme'

// 初始化暗色模式(应用 html .dark class + 持久化)
useTheme()
</script>

<template>
  <RouterView />
  <Toast />
</template>
