export interface User {
  id: string
  email: string
  username: string
  created_at: string
}

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

export interface TokenData {
  access_token: string
  token_type: string
  user: User
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[]
  error?: boolean
  createdAt: number
}

export interface Session {
  id: string
  title: string
  mode: 'chat' | 'document'
  updatedAt: number
}

/** 服务端返回的会话 DTO */
export interface SessionDto {
  id: string
  title: string
  mode: 'chat' | 'document'
  created_at: string
  updated_at: string
}

/** 服务端返回的消息 DTO */
export interface MessageDto {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface DocItem {
  id: string
  filename: string
  file_type: string
  chunk_count: number
  created_at: string
}

export interface Skill {
  name: string
  description: string
  triggers: string[]
  tools: string[]
  system_prompt_template: string
  config_schema: Record<string, unknown>
  target_agent: string
  enabled: boolean
  builtin: boolean
}

// --- 评估中心 (Phase 21, /api/v1/eval/*) ---
export type EvalVerdict = 'ok' | 'warn' | 'fail'

export interface EvalDigest {
  run_id: string | null
  layer: string
  layer_label: string
  mode: string | null
  status: string
  verdict: EvalVerdict
  score: number | null
  score_label: string | null
  failures: number
  total: number | null
  duration_ms: number | null
  created_at: string | null
}

export interface EvalRun {
  run_id: string
  layer: string
  mode: string
  status: string
  created_at: string | null
  duration_ms: number
  summary: Record<string, unknown>
  failures: Array<Record<string, unknown>>
}

export interface EvalReport {
  type: 'aggregate' | 'single'
  layers: Partial<Record<string, EvalDigest>>
  missing: string[]
  runs: EvalRun[]
}

export interface EvalHistoryItem {
  id: string
  layer: string
  mode: string
  status: string
  duration_ms: number
  created_at: string | null
  verdict: EvalVerdict
  score: number | null
  score_label: string | null
  failures: number
  total: number | null
}

export interface EvalHistory {
  items: EvalHistoryItem[]
  total: number
  layer: string | null
  limit: number
}

export interface MetricsSeries {
  kind: string
  tags: Record<string, string>
  count: number
  min: number | null
  mean: number | null
  max: number | null
  p50: number | null
  p95: number | null
  p99: number | null
  per_second: number | null
}
