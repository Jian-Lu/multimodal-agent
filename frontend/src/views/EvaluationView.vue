<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Loader2, Play, RefreshCw } from 'lucide-vue-next'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  type EvalLayer,
  type EvalMode,
  fetchHistory,
  fetchMetrics,
  fetchReport,
  fetchRun,
  runEval,
} from '@/api/eval'
import type {
  EvalDigest,
  EvalHistoryItem,
  EvalReport,
  EvalRun,
  EvalVerdict,
  MetricsSeries,
} from '@/types'
import { useToastStore } from '@/stores/toast'

const router = useRouter()
const toast = useToastStore()

const LAYERS: Array<{ key: EvalLayer; label: string }> = [
  { key: 'routing', label: '路由准确性' },
  { key: 'quality', label: '输出质量' },
  { key: 'e2e', label: 'E2E 场景' },
]

const mode = ref<EvalMode>('dry')
const selectedLayer = ref<EvalLayer>('routing')

const loading = ref(true)
const running = ref(false)
const metrics = ref<MetricsSeries[]>([])
const report = ref<EvalReport | null>(null)
const history = ref<EvalHistoryItem[]>([])
const selectedRun = ref<EvalRun | null>(null)
const detailLoading = ref(false)

onMounted(loadAll)

async function loadAll() {
  loading.value = true
  await Promise.allSettled([loadMetrics(), loadReportAndHistory()])
  loading.value = false
}

async function loadMetrics() {
  try {
    metrics.value = await fetchMetrics()
  } catch {
    /* axios 拦截器已 toast */
  }
}

async function loadReportAndHistory() {
  try {
    const [rep, his] = await Promise.all([fetchReport(), fetchHistory()])
    report.value = rep
    history.value = his.items
  } catch {
    /* axios 拦截器已 toast */
  }
}

async function onRun() {
  if (running.value) return
  running.value = true
  try {
    const res = await runEval(selectedLayer.value, mode.value)
    toast.push(
      'success',
      `评估完成 · ${selectedLayer.value}/${mode.value} · run_id=${String(res.run_id ?? '-')}`,
    )
    await Promise.all([loadMetrics(), loadReportAndHistory()])
  } catch {
    /* axios 拦截器已 toast */
  } finally {
    running.value = false
  }
}

async function onSelectHistory(item: EvalHistoryItem) {
  detailLoading.value = true
  selectedRun.value = null
  try {
    const rep = await fetchRun(item.id)
    selectedRun.value = rep.runs[0] ?? null
  } catch {
    /* axios 拦截器已 toast */
  } finally {
    detailLoading.value = false
  }
}

// ---------- 展示辅助 ----------
const VERDICT_MARK: Record<EvalVerdict, string> = { ok: '✅', warn: '⚠', fail: '❌' }

function mark(verdict: EvalVerdict | undefined): string {
  return verdict ? VERDICT_MARK[verdict] : '❌'
}

interface LatestCard {
  key: EvalLayer
  label: string
  digest: EvalDigest | null
}

const latestCards = computed<LatestCard[]>(() =>
  LAYERS.map((l) => ({
    key: l.key,
    label: l.label,
    digest: report.value?.layers?.[l.key] ?? null,
  })),
)

function digestRun(layer: EvalLayer): EvalRun | undefined {
  return report.value?.runs.find((r) => r.layer === layer)
}

function score(d: EvalDigest | null): number {
  if (!d || d.score == null) return 0
  return Math.max(0, Math.min(100, d.score))
}

function scoreText(d: EvalDigest | null): string {
  return d?.score == null ? '—' : `${fmtNum(d.score, 1)}%`
}

function metaText(d: EvalDigest | null): string {
  if (!d) return ''
  const total = d.total != null ? ` · 共 ${d.total}` : ''
  return `${d.mode ?? '-'} · ${d.status} · 失败 ${d.failures}${total} · ${fmtNum(d.duration_ms, 0)}ms · ${fmtDate(d.created_at)}`
}

interface MetricsGroup {
  kind: string
  series: MetricsSeries[]
}

const metricsGroups = computed<MetricsGroup[]>(() => {
  const map = new Map<string, MetricsSeries[]>()
  for (const s of metrics.value) {
    const arr = map.get(s.kind) ?? []
    arr.push(s)
    map.set(s.kind, arr)
  }
  return [...map.entries()].map(([kind, series]) => ({ kind, series }))
})

function fmtDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '-'
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

function tagLine(s: MetricsSeries): string {
  const parts = Object.entries(s.tags)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${v}`)
  return parts.length ? parts.join(' · ') : '(默认)'
}

function failText(fs: Array<Record<string, unknown>>): string {
  const out: string[] = []
  fs.forEach((f, i) => {
    const rawId = f.id ?? f.case_id ?? f.agent
    const label = rawId == null ? `#${i + 1}` : String(rawId)
    const reason = String(f.reason ?? f.detail ?? f.error ?? f.comment ?? '—')
    out.push(`⚠ ${label}: ${reason}`)
    for (const k of ['expected', 'actual', 'got', 'judge', 'overall', 'category']) {
      const v = f[k]
      if (v !== undefined && v !== null && v !== '' && !reason.includes(String(v))) {
        out.push(`   ${k}: ${String(v)}`)
      }
    }
    if (Array.isArray(f.checks)) {
      for (const c of f.checks as Array<Record<string, unknown>>) {
        out.push(`   ${String(c.type ?? 'check')}: ${String(c.detail ?? '')}`)
      }
    }
    if (f.error) out.push(`   error: ${String(f.error)}`)
    if (f.output_excerpt) out.push(`   excerpt: ${String(f.output_excerpt).slice(0, 200)}`)
  })
  return out.join('\n') || '（无）'
}
</script>

<template>
  <div class="min-h-screen bg-muted/40 p-6">
    <div class="mx-auto max-w-5xl">
      <div class="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="icon" title="返回工作区" @click="router.push('/')">
          <ArrowLeft class="h-4 w-4" />
        </Button>
        <h1 class="text-xl font-bold">评估中心</h1>
        <Button
          class="ml-auto"
          variant="ghost"
          size="icon"
          title="刷新"
          :disabled="loading"
          @click="loadAll"
        >
          <RefreshCw class="h-4 w-4" />
        </Button>
      </div>

      <!-- 运行条 -->
      <Card class="mb-5 p-4">
        <div class="flex flex-wrap items-center gap-3">
          <div class="flex rounded-md border border-border p-0.5">
            <button
              v-for="l in LAYERS"
              :key="l.key"
              type="button"
              :class="[
                'rounded px-3 py-1 text-sm transition-colors',
                selectedLayer === l.key
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              ]"
              @click="selectedLayer = l.key"
            >
              {{ l.label }}
            </button>
          </div>
          <div class="flex rounded-md border border-border p-0.5">
            <button
              v-for="m in (['dry', 'live'] as EvalMode[])"
              :key="m"
              type="button"
              :class="[
                'rounded px-3 py-1 text-sm transition-colors',
                mode === m
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              ]"
              @click="mode = m"
            >
              {{ m === 'dry' ? 'dry 冒烟' : 'live 真实' }}
            </button>
          </div>
          <Button class="ml-auto" :disabled="running" @click="onRun">
            <Loader2 v-if="running" class="h-4 w-4 animate-spin" />
            <Play v-else class="h-4 w-4" />
            {{ running ? '运行中…' : '运行评估' }}
          </Button>
        </div>
        <p class="mt-2 text-xs text-muted-foreground">
          dry = 离线管线冒烟(零 LLM/网络) · live = 真实模型/工具(需本机 DashScope + 对应依赖)
        </p>
      </Card>

      <!-- Layer 1 指标 -->
      <Card class="mb-5 p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="font-semibold">Layer 1 · 组件性能指标</h2>
          <span class="text-xs text-muted-foreground">最近采集 (p50 / p95 / p99)</span>
        </div>
        <p v-if="loading" class="py-4 text-center text-sm text-muted-foreground">加载中…</p>
        <Card
          v-else-if="!metricsGroups.length"
          class="p-8 text-center text-sm text-muted-foreground"
        >
          暂无指标 —— 运行一次真实对话/评估后自动采集 (仅登录态用户可看)
        </Card>
        <div v-else class="grid gap-4 lg:grid-cols-2">
          <Card v-for="g in metricsGroups" :key="g.kind" class="p-3">
            <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {{ g.kind }}
            </p>
            <div class="space-y-1.5">
              <div
                v-for="(s, i) in g.series"
                :key="i"
                class="flex items-center justify-between gap-2 text-xs"
              >
                <span class="min-w-0 truncate text-muted-foreground">{{ tagLine(s) }}</span>
                <span class="whitespace-nowrap font-mono">
                  n={{ s.count }} · {{ fmtNum(s.p50, 3) }} / {{ fmtNum(s.p95, 3) }} /
                  {{ fmtNum(s.p99, 3) }}
                </span>
              </div>
            </div>
          </Card>
        </div>
      </Card>

      <!-- 各层最新 -->
      <h2 class="mb-2 font-semibold">各层最新结果</h2>
      <p v-if="loading" class="py-4 text-center text-sm text-muted-foreground">加载中…</p>
      <div v-else class="grid gap-4 md:grid-cols-3">
        <template v-for="c in latestCards" :key="c.key">
          <Card v-if="c.digest" class="p-4">
            <div class="flex items-center justify-between">
              <h3 class="font-semibold">{{ c.label }}</h3>
              <span class="text-sm">{{ mark(c.digest.verdict) }}</span>
            </div>
            <p class="mt-1 text-xs text-muted-foreground">{{ c.digest.score_label }}</p>
            <div class="mt-2 flex items-center gap-2">
              <div class="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary transition-all"
                  :style="{ width: `${score(c.digest)}%` }"
                />
              </div>
              <span class="text-sm font-bold">{{ scoreText(c.digest) }}</span>
            </div>
            <p class="mt-2 text-xs text-muted-foreground">{{ metaText(c.digest) }}</p>
            <details v-if="(digestRun(c.key)?.failures?.length ?? 0) > 0" class="mt-2">
              <summary class="cursor-pointer text-xs text-muted-foreground">
                失败明细 ({{ digestRun(c.key)?.failures.length }})
              </summary>
              <pre
                class="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs leading-relaxed text-muted-foreground"
              >{{ failText(digestRun(c.key)?.failures ?? []) }}</pre>
            </details>
          </Card>
          <Card v-else class="flex items-center justify-center p-4 text-sm text-muted-foreground">
            {{ c.label }} · 暂无运行记录
          </Card>
        </template>
      </div>

      <!-- 单次详情 -->
      <Card v-if="selectedRun" class="mb-5 mt-5 border-primary/40 p-4">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">
            {{ mark(selectedRun.status === 'success' && !selectedRun.failures.length ? 'ok' : selectedRun.failures.length ? 'warn' : 'fail') }}
            run {{ selectedRun.run_id }}
          </h2>
          <span class="text-xs text-muted-foreground">
            {{ selectedRun.layer }} / {{ selectedRun.mode }} · {{ fmtDate(selectedRun.created_at) }}
          </span>
        </div>
        <pre
          v-if="selectedRun.failures.length"
          class="mt-2 whitespace-pre-wrap rounded-md bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground"
        >{{ failText(selectedRun.failures) }}</pre>
        <p v-else class="mt-2 text-xs text-muted-foreground">本次运行无失败项 ✅</p>
      </Card>
      <Card v-else-if="detailLoading" class="mb-5 mt-5 p-4 text-center text-sm text-muted-foreground">
        加载单次详情…
      </Card>

      <!-- 历史 -->
      <div class="mt-6 flex items-center justify-between">
        <h2 class="font-semibold">运行历史</h2>
        <span class="text-xs text-muted-foreground">共 {{ history.length }} 条 (最近)</span>
      </div>
      <p v-if="loading" class="py-4 text-center text-sm text-muted-foreground">加载中…</p>
      <Card v-else-if="!history.length" class="mt-2 p-8 text-center text-sm text-muted-foreground">
        暂无运行记录 —— 上方选择评估层并点击「运行评估」
      </Card>
      <div v-else class="mt-2 space-y-2">
        <Card
          v-for="h in history"
          :key="h.id"
          class="cursor-pointer p-3 transition-colors hover:bg-accent/40"
          @click="onSelectHistory(h)"
        >
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium">
                {{ mark(h.verdict) }} {{ h.score_label ?? h.layer }}
                <span class="ml-1 text-xs font-normal text-muted-foreground">
                  {{ h.score == null ? '' : `${fmtNum(h.score, 1)}% · ` }}{{ h.layer }}/{{ h.mode }} ·
                  {{ h.failures }} 失败
                </span>
              </p>
              <p class="text-xs text-muted-foreground">{{ fmtDate(h.created_at) }}</p>
            </div>
            <span class="whitespace-nowrap text-xs text-muted-foreground">
              {{ fmtNum(h.duration_ms, 0) }}ms
            </span>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
