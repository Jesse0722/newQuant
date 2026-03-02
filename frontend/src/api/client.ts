import axios from 'axios'

const client = axios.create({ baseURL: '/api' })

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const data = err.response?.data
    if (data?.message) {
      console.error(`[API Error] ${data.code}: ${data.message}`)
    }
    return Promise.reject(err)
  }
)

export default client
