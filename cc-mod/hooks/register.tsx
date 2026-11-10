import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// 按会话开启：默认不推送；在会话里输入 /desk-pet 打开（再输入一次关闭，也可以 /desk-pet on|off）。
// 环境变量 DESK_PET=1 启动的会话默认打开。打开时提示框右下角显示绿色「● 桌宠」。
// 打开后每个会话一个状态文件：~/.cache/desk-pet/sessions/<sessionId>.json
// state: working | reading | waiting | done | error | idle | ended
// 每 60 秒心跳重写一次；桌宠把 3 分钟没更新的文件当作已退出。
//
// 聊天：~/.cache/desk-pet/chat/<sessionId>.in.json  桌宠写 {msgs:[{id,text}|{id,answer:{qid,answers}}|{id,terminal:qid}]}
//       ~/.cache/desk-pet/chat/<sessionId>.out.json mod 写 {ack, log:[{id,role,text,src,ts}], ask, perm}
// 从桌宠发来的那一轮里，CC 的提问（选项）改到桌宠窗口回答（桌宠退出了就回到终端）。
// 权限确认始终在终端里点；桌宠窗口只提醒。
type State = 'working' | 'reading' | 'waiting' | 'done' | 'error' | 'idle' | 'ended'
type Entry = { id: number; role: 'user' | 'cc'; text: string; src: 'pet' | 'terminal'; ts: number }
type Ask = { qid: string; questions: any[] }

const ASKS_USER = new Set(['AskUserQuestion', 'ExitPlanMode'])
// 只读、查找类工具：桌宠播「低头检查」
const READS = new Set(['Read', 'Grep', 'Glob', 'LS', 'NotebookRead', 'WebFetch', 'WebSearch'])
// 用户消息里有夸奖：桌宠藏脸
const PRAISE = /谢谢|多谢|感谢|辛苦|好棒|真棒|太棒|厉害|牛|漂亮|优秀|不错|干得好|做得好|nice|great|awesome|thank|good job|well done/i

// 开关放在会话状态里：插件热重载后还在
const enabledAtom = atom({ plugin: 'desk-pet', key: 'enabled' } as const, false)

let current: State = 'idle'
let dir = ''
let sid = ''
let cwd = ''
let praised = 0
// 聊天
let ack = 0                     // 已处理的桌宠消息 id
let chatLog: Entry[] = []       // 最近的对话，写给桌宠
let ask: Ask | null = null      // 正在等桌宠回答的提问
let perm: string | null = null  // 终端里正在等批准的工具（只用来提醒）
const answers = new Map<string, any>()
let petTurn = false             // 这一轮是不是从桌宠发起的
let petTexts: string[] = []     // 从桌宠提交、还没开始的消息
let nextId = 0

async function paths($: any) {
  if (!dir) {
    const home = (await $.env.get('HOME')) ?? '/tmp'
    dir = `${home}/.cache/desk-pet`
    sid = await $.session.id()
    cwd = await $.session.cwd()
  }
  return { state: `${dir}/sessions/${sid}.json`, inbox: `${dir}/chat/${sid}.in.json`, outbox: `${dir}/chat/${sid}.out.json`, pet: `${dir}/pet.json`, cancel: `${dir}/chat/${sid}.cancel` }
}

async function readJson($: any, path: string): Promise<any> {
  try { return (await $.fs.exists(path)) ? JSON.parse(await $.fs.read(path)) : null } catch { return null }
}

// 记下状态；只有打开时才写文件。关掉那一下写 ended，让桌宠马上不算这个会话
async function write($: any, s?: State, force = false) {
  if (s) current = s
  const enabled = await read($, enabledAtom)
  if (!enabled && !force) return
  try {
    const p = await paths($)
    const state = enabled ? current : 'ended'
    await $.fs.write(p.state, JSON.stringify({ state, cwd, praised, ts: await $.clock.now() }))
  } catch {}
}

async function writeOut($: any) {
  try {
    const p = await paths($)
    await $.fs.write(p.outbox, JSON.stringify({ ack, log: chatLog.slice(-40), ask, perm }))
  } catch {}
}

async function addLog($: any, role: Entry['role'], text: string, src: Entry['src']) {
  if (!text.trim()) return
  const ts = await $.clock.now()
  nextId = Math.max(nextId + 1, ts)
  chatLog.push({ id: nextId, role, text, src, ts })
  if (chatLog.length > 40) chatLog = chatLog.slice(-40)
  await writeOut($)
}

// 桌宠活着：它每秒写 pet.json
async function petAlive($: any) {
  const v = await readJson($, (await paths($)).pet)
  return !!v && (await $.clock.now()) - (v.ts ?? 0) < 5000
}

// 每秒读一次桌宠发来的消息
async function pollInbox($: any) {
  if (!(await read($, enabledAtom))) return
  const v = await readJson($, (await paths($)).inbox)
  let changed = false
  for (const m of v?.msgs ?? []) {
    if (typeof m.id !== 'number' || m.id <= ack) continue
    ack = m.id
    changed = true
    if (typeof m.text === 'string' && m.text.trim()) {
      await addLog($, 'user', m.text, 'pet')
      petTexts.push(m.text.trim())
      void $.prompt.submit({ text: m.text, asUser: true })
    } else if (m.answer) answers.set(m.answer.qid, { answers: m.answer.answers })
    else if (m.terminal) answers.set(m.terminal, { terminal: true })
  }
  if (changed) await writeOut($)
}

// 等桌宠窗口回答：用一个小 shell 脚本等（$ 调用不占钩子的 10 秒预算，$.clock.sleep 占）。
// 收件箱里出现这个 qid 就返回；终端里先答了（cancel 文件里有这个 qid）或桌宠 5 秒没心跳就放弃。脚本一次最多等约 9.5 分钟（process.run 上限 10 分钟），共等 3 次。
const WAIT = `n=0; while [ $n -lt 1900 ]; do n=$((n+1))
  grep -q "\"$2\"" "$1" 2>/dev/null && exit 0
  grep -q "$2" "$4" 2>/dev/null && exit 4
  ts=$(grep -o '[0-9]\\+' "$3" 2>/dev/null | head -1)
  [ $(( $(date +%s%3N) - \${ts:-0} )) -gt 5000 ] && exit 2
  sleep 0.3
done; exit 3`

// 把提问交给桌宠窗口，等它回答；桌宠退出或选了「回终端答」就返回 null
async function askPet($: any, a: Ask): Promise<any> {
  ask = a
  await writeOut($)
  try {
    const p = await paths($)
    let code = 3
    for (let i = 0; i < 3 && code === 3; i++) {
      code = (await $.process.run(['sh', '-c', WAIT, 'wait', p.inbox, a.qid, p.pet, p.cancel], { timeoutMs: 600_000 })).exitCode
    }
    if (code !== 0) return null
    await pollInbox($)
    const r = answers.get(a.qid)
    answers.delete(a.qid)
    return r && !r.terminal ? r : null
  } finally {
    ask = null
    await writeOut($)
  }
}

async function setEnabled($: any, on: boolean) {
  await update($, enabledAtom, () => on)
  await write($, undefined, true)
  if (on) await writeOut($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    dir = ''
    current = 'idle'
    await $.command.register({ name: 'desk-pet', description: '桌宠跟随这个会话：开 / 关（on | off）' })
    // 热重载后接上之前的对话和已处理位置
    const old = await readJson($, (await paths($)).outbox)
    if (old) { ack = old.ack ?? 0; chatLog = old.log ?? []; nextId = chatLog.at(-1)?.id ?? 0 }
    if ((await $.env.get('DESK_PET')) === '1') await setEnabled($, true)
    $.clock.every(60_000, () => write($))
    $.clock.every(1000, () => pollInbox($))
    return r
  })

  on('command.run', { command: 'desk-pet' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    const want = arg === 'on' ? true : arg === 'off' ? false : !(await read($, enabledAtom))
    await setEnabled($, want)
    return { text: want ? '桌宠开始跟随这个会话，双击桌宠可以在小窗里聊天。再输入 /desk-pet 关闭。' : '桌宠不再跟随这个会话。' }
  })

  // 打开时在提示框右下角的模式标签后面加一个绿色「● 桌宠」
  on('ui.render', { component: 'SessionMode' }, async ($, e, next) => {
    if (!(await read($, enabledAtom))) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const modes = e.props.modes
    return (
      <Box>
        {modes.length > 0 ? <Text dimColor>{modes.join(' & ')} & </Text> : null}
        <Text color="success">● 桌宠</Text>
      </Box>
    )
  })

  on('session.end', async ($, e, next) => {
    await write($, 'ended')
    dir = ''
    return next(e)
  })

  // 终端里打的字也同步到桌宠窗口（斜杠命令不算）
  on('prompt.submit', async ($, e, next) => {
    const o: any = (e as any).origin
    // 先记下再 next：next 要等这一轮跑完才返回。（本插件自己提交的不会经过这里）
    if (o?.kind !== 'plugin' && !(e as any).command && !e.text.startsWith('/') && (await read($, enabledAtom))) {
      await addLog($, 'user', e.text, 'terminal')
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) {
      // 这一轮的文字是刚从桌宠提交的那条：算桌宠发起的
      const i = petTexts.indexOf(e.text.trim())
      petTurn = i >= 0
      if (i >= 0) petTexts.splice(i, 1)
      if (PRAISE.test(e.text)) praised = await $.clock.now()
      await write($, 'working')
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) {
      await write($, e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'idle' : 'error')
      if (await read($, enabledAtom)) {
        const text = e.reason === 'answer' ? (e as any).answer ?? '' : e.reason === 'aborted' ? '（这一轮被中断了）' : '（这一轮出错了）'
        await addLog($, 'cc', text, petTurn ? 'pet' : 'terminal')
      }
    }
    return next(e)
  })

  // 等你批准：只在真的弹出权限对话框给人时才算（auto 模式下被自动放行的不会触发）
  // 工具权限只能在终端里批准；这里只把「在等哪个工具」告诉桌宠窗口。
  // 例外是 AskUserQuestion：它的「对话框」就是提问本身。从桌宠发起的这一轮，选项显示在桌宠窗口里，
  // 选好的答案按这个工具的约定放进 updatedInput.answers 交回去（只回答提问，不批准任何别的工具）。
  on('classic.PermissionRequest', async ($, e, next) => {
    const ev: any = e
    if (ev.agent_id) return next(e)
    await write($, 'waiting')
    if (ev.tool_name === 'AskUserQuestion' && petTurn && (await read($, enabledAtom)) && (await petAlive($))) {
      const questions = (ev.tool_input?.questions ?? []) as any[]
      const r = await askPet($, { qid: `q${await $.clock.now()}`, questions })
      if (r) {
        await write($, 'working')
        return { decision: { behavior: 'allow', updatedInput: { ...ev.tool_input, answers: r.answers ?? {} } } }
      }
      return next(e)
    }
    perm = ev.tool_name ?? '工具'
    await writeOut($)
    try { return await next(e) } finally { perm = null; await writeOut($) }
  }).catch(($, e, next) => next(e))   // 桌宠出错也不能挡住权限流程

  on('tool.call', async ($, e, next) => {
    const main = !(e as any).agentId
    if (main) await write($, ASKS_USER.has(e.tool) ? 'waiting' : READS.has(e.tool) ? 'reading' : 'working')
    const r = await next(e)
    // 提问在终端里先答了：收起桌宠窗口里的选项
    if (main && e.tool === 'AskUserQuestion' && ask) {
      try { await $.fs.write((await paths($)).cancel, ask.qid) } catch {}
      ask = null
      await writeOut($)
    }
    // 等人（权限、提问）结束要改回工作中；查看中保持到下一个工具或回合结束，免得来回切
    if (main && current === 'waiting') await write($, 'working')
    return r
  }).catch(($, e, next) => next(e))   // 桌宠出错也不能挡住工具调用
}
