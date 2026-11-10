import type { Register } from 'claude-code'

// 每个会话一个状态文件：~/.cache/desk-pet/sessions/<sessionId>.json
// state: working | reading | waiting | done | error | idle | ended
// 每 60 秒心跳重写一次；桌宠把 3 分钟没更新的文件当作已退出。
type State = 'working' | 'reading' | 'waiting' | 'done' | 'error' | 'idle' | 'ended'

const ASKS_USER = new Set(['AskUserQuestion', 'ExitPlanMode'])
// 只读、查找类工具：桌宠播「低头检查」
const READS = new Set(['Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'WebFetch', 'WebSearch'])

let current: State = 'idle'
let file: string | undefined
let cwd = ''

async function write($: any, s?: State) {
  if (s) current = s
  try {
    if (!file) {
      const home = (await $.env.get('HOME')) ?? '/tmp'
      file = `${home}/.cache/desk-pet/sessions/${await $.session.id()}.json`
      cwd = await $.session.cwd()
    }
    await $.fs.write(file, JSON.stringify({ state: current, cwd, ts: await $.clock.now() }))
  } catch {}
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    file = undefined
    await write($, 'idle')
    $.clock.every(60_000, () => write($))
    return r
  })

  on('session.end', async ($, e, next) => {
    await write($, 'ended')
    file = undefined
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) await write($, 'working')
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) {
      await write($, e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'idle' : 'error')
    }
    return next(e)
  })

  // 权限询问：判定结果是 ask 就是在等人
  on('tool.check', async ($, e, next) => {
    const r = await next(e)
    if (e.tool_use_id && !e.agentId && r.decision === 'ask') await write($, 'waiting')
    return r
  })

  on('tool.call', async ($, e, next) => {
    const main = !(e as any).agentId
    if (main) await write($, ASKS_USER.has(e.tool) ? 'waiting' : READS.has(e.tool) ? 'reading' : 'working')
    const r = await next(e)
    // 只有等人（权限、提问）结束要改回工作中；查看中保持到下一个工具或回合结束，免得来回切
    if (main && current === 'waiting') await write($, 'working')
    return r
  })
}
