import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// 按会话开启：默认不推送；在会话里输入 /desk-pet 打开（再输入一次关闭，也可以 /desk-pet on|off）。
// 环境变量 DESK_PET=1 启动的会话默认打开。打开时提示框右下角显示绿色「● 桌宠」。
// 打开后每个会话一个状态文件：~/.cache/desk-pet/sessions/<sessionId>.json
// state: working | reading | waiting | done | error | idle | ended
// 每 60 秒心跳重写一次；桌宠把 3 分钟没更新的文件当作已退出。
//
// 聊天：~/.cache/desk-pet/chat/<sessionId>.in.json  桌宠写 {msgs:[{id,text,prompt?,media?}|{id,answer:{qid,answers}}|{id,terminal:qid}]}
//       ~/.cache/desk-pet/chat/<sessionId>.out.json mod 写 {ack, log:[{id,role,text,src,ts}], ask, perm}
// 从桌宠发来的那一轮里，CC 的提问（选项）改到桌宠窗口回答（桌宠退出了就回到终端）。
// 权限确认始终在终端里点；桌宠窗口只提醒。
type State = 'working' | 'reading' | 'waiting' | 'done' | 'error' | 'idle' | 'ended'
type Entry = { id: number; role: 'user' | 'cc'; text: string; src: 'pet' | 'terminal'; ts: number; media?: any[] }
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
let activity = ''               // CC 正在做什么，给桌宠窗口页尾那一行
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
    await $.fs.write(p.outbox, JSON.stringify({ ack, log: chatLog.slice(-40), ask, perm, activity }))
  } catch {}
}

async function addLog($: any, role: Entry['role'], text: string, src: Entry['src'], media?: any[]) {
  if (!text.trim() && !media?.length) return
  const ts = await $.clock.now()
  nextId = Math.max(nextId + 1, ts)
  chatLog.push({ id: nextId, role, text, src, ts, ...(media?.length ? { media } : {}) })
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
    // 一条消息：显示用 text（和图片 media），发给 CC 用 prompt（带图片路径）
    const prompt = typeof m.prompt === 'string' && m.prompt.trim() ? m.prompt : typeof m.text === 'string' ? m.text : ''
    if (prompt.trim()) {
      await addLog($, 'user', m.text ?? '', 'pet', Array.isArray(m.media) ? m.media : undefined)
      petTexts.push(prompt.trim())
      void $.prompt.submit({ text: prompt, asUser: true })
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

// CC 转圈提示的英文词（Brewing、Pondering……）翻成西幻日常风：思考时页尾显示「正在煮一壶红茶…」
const SPINNER_WORDS: Record<string, string> = { "accomplishing": "把手头的活收尾", "actioning": "卷起袖子干活", "actualizing": "把想法写进手账", "baking": "烤一炉黑麦面包", "beaming": "在窗边晒太阳", "befuddling": "对着账本犯迷糊", "bloviating": "在酒馆里听人吹牛", "boogieing": "在丰收节上跳舞", "boondoggling": "替修道院长跑腿", "booping": "戳一戳打盹的猫", "brewing": "煮一壶红茶", "burrowing": "钻进被窝", "calculating": "用算盘对账", "canoodling": "抱着猫取暖", "caramelizing": "熬一锅焦糖", "cascading": "看喷泉的水落下来", "catapulting": "帮孩子们修弹弓", "cerebrating": "托着腮想事情", "channeling": "把雨水引进水缸", "channelling": "把雨水引进水缸", "choreographing": "排练节日的圣诗队形", "churning": "搅黄油", "clambering": "爬上钟楼", "clauding": "向窗外的鸽子问好", "coalescing": "把散落的纸页理整齐", "cogitating": "对着烛火想事情", "combobulating": "把拆开的钟表装回去", "composing": "写一首赞美诗", "computing": "数今天卖了几个面包", "concocting": "调一杯蜂蜜柠檬水", "considering": "掂量着该怎么办", "contemplating": "望着窗外发呆", "cooking": "炖一锅蔬菜汤", "crafting": "编一个柳条篮子", "creating": "动手做点东西", "crunching": "嚼一块硬饼干", "crystallizing": "等蜂蜜结晶", "cultivating": "给菜园松土", "deciphering": "辨认老信上的字", "deliberating": "和修女们商量", "determining": "下定决心", "dilly-dallying": "在回廊里磨蹭", "discombobulating": "被打乱了思路", "divining": "看天色猜明天下不下雨", "doing": "忙着手上的事", "doodling": "在书页边上涂鸦", "drizzling": "给面包淋上蜂蜜", "ebbing": "在码头等退潮", "effecting": "把计划付诸行动", "elucidating": "把事情讲明白", "embellishing": "给信纸画上花边", "enchanting": "给窗台的花浇水", "envisioning": "想象明天的集市", "evaporating": "晾干洗好的衣服", "fermenting": "酿一坛苹果酒", "fiddle-faddling": "和邻居闲聊", "finagling": "在集市上砍价", "flambéing": "点燃壁炉", "flibbertigibbeting": "叽叽喳喳说个不停", "flowing": "顺着小溪散步", "flummoxing": "被难住了", "fluttering": "追蝴蝶", "forging": "去铁匠铺打马蹄铁", "forming": "捏面团", "frolicking": "在草地上打滚", "frosting": "给蛋糕抹糖霜", "gallivanting": "在镇上闲逛", "galloping": "骑马去邻村", "garnishing": "给汤撒点香草", "generating": "琢磨点新花样", "germinating": "等种子发芽", "gesticulating": "比划着解释", "gitifying": "把信件归档", "grooving": "哼着小曲", "gusting": "关好被风吹开的窗", "harmonizing": "和唱诗班合音", "hashing": "切土豆丁", "hatching": "等母鸡孵蛋", "herding": "把羊赶回圈里", "honking": "被大鹅追着跑", "hullaballooing": "筹备节日宴会", "hustling": "赶早集", "hyperspacing": "抄近路穿过小巷", "ideating": "想点子", "imagining": "做白日梦", "improvising": "随手哼一段", "incubating": "给小鸡保暖", "inferring": "顺着线索推一推", "infusing": "泡一杯薄荷茶", "ionizing": "看窗外打雷", "jitterbugging": "踩着鼓点跳舞", "jiving": "跟着手风琴跳舞", "julienning": "把胡萝卜切成丝", "kneading": "揉面团", "leavening": "等面团发起来", "levitating": "踮着脚够书架顶层", "lollygagging": "在酒馆坐着发呆", "manifesting": "把心愿写在纸条上", "marinating": "腌一罐酸黄瓜", "meandering": "沿着河边散步", "metamorphosing": "换上节日的衣裳", "misting": "看晨雾散开", "moonwalking": "月下散步", "moseying": "在回廊里慢慢走", "mulling": "温一壶香料酒", "mustering": "把大家叫来吃饭", "musing": "出神地想着什么", "nebulizing": "看炉子冒出的热气", "nesting": "把窝铺得软软的", "noodling": "随手拨弄鲁特琴", "nucleating": "等糖水结晶", "orbiting": "绕着集市转了一圈", "orchestrating": "安排节日的分工", "osmosing": "在图书室泡了一下午", "perambulating": "在修道院里巡一圈", "percolating": "滤一壶咖啡", "perusing": "翻祷告书", "philosophising": "和老修士聊人生", "philosophizing": "和老修士聊人生", "photosynthesizing": "在花园里晒太阳", "pollinating": "看蜜蜂采蜜", "pondering": "托着腮想事情", "pontificating": "听神父布道", "pouncing": "看猫扑麻雀", "precipitating": "收好晾着的衣服", "prestidigitating": "给孩子们变个小戏法", "processing": "处理手头的事", "proofing": "等面团醒好", "propagating": "给花分株", "puttering": "在花园里东摸西摸", "puzzling": "对着谜语抓头", "quantumizing": "数天上的星星", "razzle-dazzling": "把烛台擦得亮晶晶", "razzmatazzing": "把烛台擦得亮晶晶", "recombobulating": "重新理清思路", "reticulating": "织一张渔网", "roosting": "在钟楼上看鸽子", "ruminating": "慢慢回想白天的事", "sautéing": "煎几片培根", "sauteing": "煎几片培根", "scampering": "一路小跑", "schlepping": "搬一筐苹果", "scheming": "盘算明天的安排", "scurrying": "跑去地窖拿东西", "seasoning": "往汤里加盐", "shenaniganing": "和孩子们捣蛋", "shimmying": "从篱笆缝里钻过去", "shucking": "剥豌豆", "simmering": "小火炖汤", "skedaddling": "溜回房间", "sketching": "画一幅修道院的速写", "slithering": "绕开路上的泥坑", "smooshing": "捣土豆泥", "sock-hopping": "穿着袜子在走廊滑", "spelunking": "下地窖找东西", "spinning": "纺羊毛线", "sprouting": "看豆芽冒头", "stewing": "炖一锅牛肉", "stirring": "搅一搅锅里的汤", "sublimating": "把烦恼写进日记", "sussing": "琢磨是怎么回事", "swirling": "转着茶杯", "swooping": "看燕子掠过屋檐", "symbioting": "和猫分享一个靠垫", "synthesizing": "把笔记理成一页", "tempering": "看铁匠淬火", "thaumaturging": "为病人祈祷", "thinking": "想一想", "thundering": "听窗外打雷", "tinkering": "修那把吱呀响的椅子", "tomfoolering": "做鬼脸逗孩子笑", "topsy-turvying": "把房间翻了个底朝天", "transfiguring": "换一身干净的修女服", "transmuting": "把剩饭做成新菜", "twisting": "拧干洗好的衣服", "undulating": "看麦浪起伏", "unfurling": "展开一卷旧地图", "unravelling": "解开缠在一起的毛线", "unraveling": "解开缠在一起的毛线", "vibing": "听着雨声放空", "waddling": "跟在鸭子后面走", "wandering": "在镇上四处转转", "warping": "把木板压平", "whatchamacalliting": "找那个叫不上名字的东西", "whirlpooling": "洗衣盆里搅出个漩涡", "whirring": "摇纺车", "whisking": "打蛋液", "wibbling": "晃一晃果冻", "wizarding": "看街头艺人变戏法", "working": "忙活", "wrangling": "把跑出来的山羊抓回去", "zesting": "刨柠檬皮", "zigzagging": "在小巷里绕来绕去" }
const SPINNER_FALLBACK = ['点上一支蜡烛', '翻开祷告书', '泡一壶茶', '整理书架', '给花浇水', '擦一擦烛台']
function fantasy(word: string): string {
  const w = String(word ?? '').trim().replace(/[.…]+$/, '').toLowerCase()
  if (SPINNER_WORDS[w]) return SPINNER_WORDS[w]
  let h = 0
  for (const ch of w) h = (h * 31 + ch.charCodeAt(0)) | 0
  return SPINNER_FALLBACK[Math.abs(h) % SPINNER_FALLBACK.length]
}

// 工具调用说成人话：读 chat.py、跑命令：npm test、搜索「foo」……
function describe(e: any): string {
  const base = (f: any) => String(f ?? '').split('/').filter(Boolean).pop() ?? ''
  const cut = (x: any, n = 40) => { const t = String(x ?? '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n) + '…' : t }
  switch (e.tool) {
    case 'Read': return `读 ${base(e.file_path)}`
    case 'Edit': case 'MultiEdit': case 'NotebookEdit': return `改 ${base(e.file_path ?? e.notebook_path)}`
    case 'Write': return `写 ${base(e.file_path)}`
    case 'Bash': return `跑命令：${cut(e.description || e.command)}`
    case 'Grep': return `搜索「${cut(e.pattern, 24)}」`
    case 'Glob': return `找文件 ${cut(e.pattern, 30)}`
    case 'WebFetch': { try { return `看网页 ${new URL(e.url).host}` } catch { return '看网页' } }
    case 'WebSearch': return `上网搜「${cut(e.query, 24)}」`
    case 'Agent': case 'Task': return `派子任务：${cut(e.description, 30)}`
    case 'TodoWrite': return '整理待办'
    case 'AskUserQuestion': return '等你回答'
    default: return `用 ${e.tool}`
  }
}

async function setActivity($: any, a: string) {
  if (a === activity) return
  activity = a
  if (await read($, enabledAtom)) await writeOut($)
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

  // 思考时（没在用工具）：读转圈提示当前的词，翻成西幻日常风给桌宠窗口；提示本身原样画
  on('ui.render', { component: 'Spinner' }, async ($, e, next) => {
    const pr: any = e.props
    if (pr.mode !== 'tool-use' && pr.mode !== 'tool-input' && pr.word && (await read($, enabledAtom))) {
      await setActivity($, fantasy(pr.word))
    }
    return next(e)
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
      await setActivity($, '想一想')
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) {
      await write($, e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'idle' : 'error')
      activity = ''
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
    if (main) {
      await write($, ASKS_USER.has(e.tool) ? 'waiting' : READS.has(e.tool) ? 'reading' : 'working')
      await setActivity($, describe(e))
    }
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
