const AUTH_KEY = 'newquant:auth'
const DEFAULT_USERNAME = 'admin'
const DEFAULT_PASSWORD = 'admin123'

export interface AuthSession {
  username: string
  loginAt: string
}

export const getAuthSession = (): AuthSession | null => {
  try {
    const raw = window.localStorage.getItem(AUTH_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthSession
    return parsed?.username === DEFAULT_USERNAME ? parsed : null
  } catch {
    return null
  }
}

export const isAuthenticated = () => Boolean(getAuthSession())

export const login = (username: string, password: string): AuthSession | null => {
  if (username.trim() !== DEFAULT_USERNAME || password !== DEFAULT_PASSWORD) {
    return null
  }
  const session = {
    username: DEFAULT_USERNAME,
    loginAt: new Date().toISOString(),
  }
  window.localStorage.setItem(AUTH_KEY, JSON.stringify(session))
  return session
}

export const logout = () => {
  window.localStorage.removeItem(AUTH_KEY)
}
