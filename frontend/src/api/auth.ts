import type { TokenData, User } from '@/types'

import client from './client'

export async function login(email: string, password: string): Promise<TokenData> {
  const res = await client.post('/api/v1/auth/login', { email, password })
  return res.data as TokenData
}

export async function register(email: string, username: string, password: string): Promise<User> {
  const res = await client.post('/api/v1/auth/register', { email, username, password })
  return res.data as User
}
