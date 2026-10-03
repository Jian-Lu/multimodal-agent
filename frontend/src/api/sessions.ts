import type { MessageDto, SessionDto } from '@/types'

import client from './client'

/** 拉取当前用户的历史会话(服务端为准)。 */
export async function fetchSessions(): Promise<SessionDto[]> {
  const res = await client.get('/api/v1/sessions')
  return res.data as SessionDto[]
}

/** 拉取某会话的消息(按时间正序)。 */
export async function fetchSessionMessages(sessionId: string): Promise<MessageDto[]> {
  const res = await client.get(`/api/v1/sessions/${sessionId}/messages`)
  return res.data as MessageDto[]
}

/** 删除某会话(服务端级联删除其消息)。 */
export async function removeSession(sessionId: string): Promise<void> {
  await client.delete(`/api/v1/sessions/${sessionId}`)
}
