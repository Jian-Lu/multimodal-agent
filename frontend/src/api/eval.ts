import type { EvalHistory, EvalReport, MetricsSeries } from '@/types'

import client from './client'

export type EvalLayer = 'routing' | 'quality' | 'e2e'
export type EvalMode = 'live' | 'dry'

const BASE = '/api/v1/eval'

/** Layer 1 实时性能指标 (collector 快照 = per-kind+tags 的 series 列表)。 */
export async function fetchMetrics(): Promise<MetricsSeries[]> {
  const res = await client.get(`${BASE}/metrics`)
  return res.data as MetricsSeries[]
}

/** 触发一次评估 (layer/mode 为 query 参数)。 */
export async function runEval(layer: EvalLayer, mode: EvalMode): Promise<Record<string, unknown>> {
  const res = await client.post(`${BASE}/run`, null, { params: { layer, mode } })
  return res.data as Record<string, unknown>
}

/** 各层最新聚合报告。 */
export async function fetchReport(): Promise<EvalReport> {
  const res = await client.get(`${BASE}/report`)
  return res.data as EvalReport
}

/** 精确某次 run 的完整报告。 */
export async function fetchRun(runId: string): Promise<EvalReport> {
  const res = await client.get(`${BASE}/report`, { params: { run_id: runId } })
  return res.data as EvalReport
}

/** 运行历史 (按时间降序, 可 layer 过滤)。 */
export async function fetchHistory(layer?: EvalLayer): Promise<EvalHistory> {
  const res = await client.get(`${BASE}/report/history`, { params: layer ? { layer } : {} })
  return res.data as EvalHistory
}
