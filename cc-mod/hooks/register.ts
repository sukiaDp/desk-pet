import type { Register } from 'claude-code'

// 按会话开启：默认不推送；在会话里输入 /desk-pet 打开（再输入一次关闭，也可以 /desk-pet on|off）。
// 环境变量 DESK_PET=1 启动的会话默认打开。
// 打开后每个会话一个状态文件：~/.cache/desk-pet/sessions/<sessionId>.json
// state: working | reading | waiting | done | error | idle | ended
// 每 60 秒心跳重写一次；桌宠把 3 分钟没更新的文件当作已退出。
type State = 'working' | 'reading' | 'waiting' | 'done' | 'error' | 'idle' | 'ended'

const ASKS_USER = new Set(['AskUserQuestion', 'ExitPlanMode'])
// 只读、查找类工具：桌宠播「低头检查」
const READS = new Set(['Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'WebFetch', 'WebSearch'])
// 用户消息里有夸奖：桌宠藏脸
const PRAISE = /谢谢|多谢|感谢|辛苦|好棒|真棒|太棒|厉害|牛|漂亮|优秀|不错|干得好|做得好|nice|great|awesome|thank|good job|well done/i

let enabled = false
let current: State = 'idle'
let file: string | undefined
let cwd = ''
let praised = 0

// 记下状态；只有打开时才写文件（关掉那一下写 ended，让桌宠马上不算这个会话）
async function write($: any, s?: State, force = false) {
  if (s) current = s
  if (!enabled && !force) return
  try {
    if (!file) {
      const home = (await $.env.get('HOME')) ?? '/tmp'
      file = `${home}/.cache/desk-pet/sessions/${await $.session.id()}.json`
      cwd = await $.session.cwd()
    }
    const state = enabled ? current : 'ended'
    await $.fs.write(file, JSON.stringify({ state, cwd, praised, ts: await $.clock.now() }))
  } catch {}
}

async function setEnabled($: any, on: boolean) {
  enabled = on
  await write($, undefined, true)
  $.ui.status(on ? '桌宠：开' : undefined)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    file = undefined
    current = 'idle'
    await $.command.register({ name: 'desk-pet', description: '桌宠跟随这个会话：开 / 关（on | off）' })
    if ((await $.env.get('DESK_PET')) === '1') await setEnabled($, true)
    $.clock.every(60_000, () => write($))
    return r
  })

  on('command.run', { command: 'desk-pet' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    const want = arg === 'on' ? true : arg === 'off' ? false : !enabled
    await setEnabled($, want)
    return { text: want ? '桌宠开始跟随这个会话。再输入 /desk-pet 关闭。' : '桌宠不再跟随这个会话。' }
  })

  on('session.end', async ($, e, next) => {
    if (enabled) await write($, 'ended')
    file = undefined
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) {
      if (PRAISE.test(e.text)) praised = await $.clock.now()
      await write($, 'working')
    }
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
