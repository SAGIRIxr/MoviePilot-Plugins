<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['save', 'close', 'switch'])

const PLUGIN_ID = 'DiscordMsgForward'

const DOCS_URL =
  'https://github.com/SAGIRIxr/MoviePilot-Plugins/blob/main/plugins.v2/discordmsgforward/README.md'

function defaultRule() {
  return {
    id: Math.random().toString(36).slice(2, 10),
    name: '',
    enabled: true,
    channels: [],
    notify_enabled: true,
    notify_channels: [],
    forward_channels: [],
    discord_template: '',
    keywords: '',
    blocked_keywords: '',
    author_include: '',
    author_exclude: '',
    code_regex: '',
    aggregate: true,
    forward_image: true,
    jump_link: true,
    dedup: false,
    quiet_hours: '',
    title_template: '',
    text_template: '',
  }
}

const config = reactive({
  enabled: false,
  token: '',
  use_proxy: true,
  interval: 5,
  msgtype: 'Plugin',
  fail_alert: true,
  history_days: 30,
  ...props.initialConfig,
  rules: (props.initialConfig?.rules || []).map(r => ({ ...defaultRule(), ...r })),
})

const channelOptions = ref([])
const notifierOptions = ref([])
const msgtypeOptions = ref([])
const regexPresets = ref([])
const loadingChannels = ref(false)
const showToken = ref(false)
const message = ref('')
const messageType = ref('info')

// 规则编辑弹窗
const dialog = ref(false)
const editIndex = ref(-1)
const editRule = ref(defaultRule())

// 删除确认
const deleteDialog = ref(false)
const deleteIndex = ref(-1)

// 手动添加频道 ID
const manualChannel = ref('')
const manualForward = ref('')

function addManualId(source, field) {
  const cid = source.value.trim()
  if (!/^\d{5,}$/.test(cid)) {
    showMessage('频道 ID 应为纯数字', 'error')
    return
  }
  if (!editRule.value[field].includes(cid)) {
    editRule.value[field].push(cid)
  }
  source.value = ''
}

function addManualChannel() {
  addManualId(manualChannel, 'channels')
}

function addManualForward() {
  addManualId(manualForward, 'forward_channels')
}

function applyPreset(preset) {
  editRule.value.code_regex = preset.value
  showMessage(`已填入「${preset.title}」正则`, 'success')
}

const channelNameMap = computed(() => {
  const map = {}
  channelOptions.value.forEach(o => { map[o.value] = o.title })
  return map
})

function channelName(cid) {
  return channelNameMap.value[cid] || cid
}

function showMessage(text, type = 'info') {
  message.value = text
  messageType.value = type
  setTimeout(() => { message.value = '' }, 4000)
}

async function loadOptions() {
  try {
    const [notifiers, msgtypes, presets] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/notifiers`),
      props.api.get(`plugin/${PLUGIN_ID}/msgtypes`),
      props.api.get(`plugin/${PLUGIN_ID}/regex_presets`),
    ])
    notifierOptions.value = notifiers?.options || []
    msgtypeOptions.value = msgtypes?.options || []
    regexPresets.value = presets?.options || []
  } catch (e) {
    console.error('加载选项失败', e)
  }
}

async function loadChannels(refresh = false) {
  loadingChannels.value = true
  try {
    const res = await props.api.get(`plugin/${PLUGIN_ID}/channels`, { params: { refresh } })
    channelOptions.value = res?.options || []
    if (refresh) {
      showMessage(`已刷新，共 ${channelOptions.value.length} 个频道`, 'success')
    }
  } catch (e) {
    console.error('加载频道失败', e)
    if (refresh) showMessage('刷新频道列表失败，请检查 Token 和代理', 'error')
  } finally {
    loadingChannels.value = false
  }
}

function addRule() {
  editIndex.value = -1
  editRule.value = defaultRule()
  dialog.value = true
}

function openRule(index) {
  editIndex.value = index
  editRule.value = JSON.parse(JSON.stringify(config.rules[index]))
  dialog.value = true
}

function confirmRule() {
  if (!editRule.value.name) {
    editRule.value.name = `规则 ${config.rules.length + 1}`
  }
  if (!editRule.value.notify_enabled && !editRule.value.forward_channels.length) {
    showMessage('请至少选择一个去向：推送到通知渠道，或转发到 Discord 频道', 'error')
    return
  }
  if (editIndex.value >= 0) {
    config.rules.splice(editIndex.value, 1, JSON.parse(JSON.stringify(editRule.value)))
  } else {
    config.rules.push(JSON.parse(JSON.stringify(editRule.value)))
  }
  dialog.value = false
}

function askDelete(index) {
  deleteIndex.value = index
  deleteDialog.value = true
}

function confirmDelete() {
  if (deleteIndex.value >= 0) {
    config.rules.splice(deleteIndex.value, 1)
  }
  deleteDialog.value = false
  deleteIndex.value = -1
}

function ruleTargetSummary(rule) {
  const parts = []
  if (rule.notify_enabled) {
    parts.push(rule.notify_channels.length ? rule.notify_channels.join('、') : '全部通知渠道')
  }
  if (rule.forward_channels?.length) {
    parts.push('Discord: ' + rule.forward_channels.map(channelName).join('、'))
  }
  return parts.length ? parts.join('　+　') : '未选去向'
}

function ruleFilterSummary(rule) {
  const parts = []
  if (rule.keywords) parts.push(`关键词:${rule.keywords}`)
  if (rule.blocked_keywords) parts.push(`屏蔽:${rule.blocked_keywords}`)
  if (rule.author_include) parts.push(`作者:${rule.author_include}`)
  if (rule.author_exclude) parts.push(`排除作者:${rule.author_exclude}`)
  if (rule.code_regex) parts.push('提取正则')
  if (rule.dedup) parts.push('去重')
  if (rule.jump_link === false) parts.push('无跳转链接')
  return parts.join('　')
}

function saveConfig() {
  if (!config.token) {
    showMessage('请填写 Bot Token', 'error')
    return
  }
  emit('save', JSON.parse(JSON.stringify(config)))
}

onMounted(() => {
  loadOptions()
  loadChannels(false)
})
</script>

<template>
  <div class="plugin-config">
    <v-alert v-if="message" :type="messageType" variant="tonal" density="compact" class="mb-3">
      {{ message }}
    </v-alert>

    <!-- 全局设置 -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-cog</v-icon>
        全局设置
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-row dense>
          <v-col cols="12" md="3">
            <v-switch v-model="config.enabled" label="启用插件" color="primary" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-switch v-model="config.use_proxy" label="使用系统代理" color="warning" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-switch v-model="config.fail_alert" label="失败告警" color="error" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-text-field
              v-model.number="config.interval" label="轮询间隔(分钟)" type="number"
              density="compact" variant="outlined" prepend-inner-icon="mdi-timer-outline" hide-details
            />
          </v-col>
        </v-row>
        <v-row dense class="mt-2">
          <v-col cols="12" md="6">
            <v-text-field
              v-model="config.token" label="Bot Token"
              :type="showToken ? 'text' : 'password'"
              :append-inner-icon="showToken ? 'mdi-eye-off' : 'mdi-eye'"
              density="compact" variant="outlined" prepend-inner-icon="mdi-key"
              hint="保存后自动拉取 Bot 可见频道列表" persistent-hint
              autocomplete="new-password"
              @click:append-inner="showToken = !showToken"
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-select
              v-model="config.msgtype" label="通知类型" :items="msgtypeOptions"
              item-title="title" item-value="value"
              density="compact" variant="outlined" prepend-inner-icon="mdi-bell-outline"
              hint="所选通知渠道需开启该类型开关" persistent-hint
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-text-field
              v-model.number="config.history_days" label="历史保留天数" type="number"
              density="compact" variant="outlined" prepend-inner-icon="mdi-history" hide-details
            />
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 转发规则 -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-swap-horizontal</v-icon>
        转发规则
        <v-spacer />
        <v-btn
          size="small" variant="tonal" color="info" class="mr-2"
          :loading="loadingChannels" prepend-icon="mdi-refresh"
          @click="loadChannels(true)"
        >
          刷新频道列表
        </v-btn>
        <v-btn size="small" color="primary" prepend-icon="mdi-plus" @click="addRule">
          添加规则
        </v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-alert v-if="!config.rules.length" type="info" variant="tonal">
          还没有转发规则，点击右上角「添加规则」创建第一条：选择监听频道和转发渠道即可。
        </v-alert>
        <v-row v-else dense>
          <v-col v-for="(rule, index) in config.rules" :key="rule.id" cols="12" md="6" lg="4">
            <v-card variant="tonal" :color="rule.enabled ? 'primary' : undefined" class="rule-card">
              <v-card-item>
                <template #prepend>
                  <v-icon :color="rule.enabled ? 'primary' : 'grey'">
                    {{ rule.enabled ? 'mdi-send-circle' : 'mdi-send-lock' }}
                  </v-icon>
                </template>
                <v-card-title class="text-subtitle-1">{{ rule.name || '未命名规则' }}</v-card-title>
                <template #append>
                  <v-switch
                    v-model="rule.enabled" color="primary" density="compact" hide-details
                    @click.stop
                  />
                </template>
              </v-card-item>
              <v-card-text class="pt-0">
                <div class="mb-1">
                  <v-chip
                    v-for="cid in rule.channels.slice(0, 3)" :key="cid"
                    size="x-small" variant="outlined" class="mr-1 mb-1"
                  >
                    {{ channelName(cid) }}
                  </v-chip>
                  <v-chip v-if="rule.channels.length > 3" size="x-small" variant="text" class="mb-1">
                    +{{ rule.channels.length - 3 }}
                  </v-chip>
                  <v-chip v-if="!rule.channels.length" size="x-small" color="warning" variant="tonal" class="mb-1">
                    未选频道
                  </v-chip>
                </div>
                <div class="text-caption mb-1 text-truncate">
                  <v-icon size="x-small" class="mr-1">mdi-send</v-icon>
                  {{ ruleTargetSummary(rule) }}
                  <v-icon v-if="rule.quiet_hours" size="x-small" class="ml-2 mr-1">mdi-sleep</v-icon>
                  <span v-if="rule.quiet_hours">{{ rule.quiet_hours }}</span>
                </div>
                <div v-if="ruleFilterSummary(rule)" class="text-caption text-truncate">
                  <v-icon size="x-small" class="mr-1">mdi-filter</v-icon>
                  {{ ruleFilterSummary(rule) }}
                </div>
              </v-card-text>
              <v-card-actions class="pt-0">
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-pencil" @click="openRule(index)">
                  编辑
                </v-btn>
                <v-btn size="small" variant="text" color="error" prepend-icon="mdi-delete" @click="askDelete(index)">
                  删除
                </v-btn>
              </v-card-actions>
            </v-card>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 操作按钮 -->
    <div class="d-flex">
      <v-btn
        variant="text" color="primary" prepend-icon="mdi-book-open-variant"
        :href="DOCS_URL" target="_blank" rel="noopener noreferrer"
      >
        使用说明
      </v-btn>
      <v-spacer />
      <v-btn class="mr-2" variant="text" @click="emit('switch')">详情页</v-btn>
      <v-btn class="mr-2" variant="text" @click="emit('close')">关闭</v-btn>
      <v-btn color="primary" prepend-icon="mdi-content-save" @click="saveConfig">保存配置</v-btn>
    </div>

    <!-- 规则编辑弹窗 -->
    <v-dialog v-model="dialog" max-width="800" scrollable>
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon color="info" class="mr-2">{{ editIndex >= 0 ? 'mdi-pencil' : 'mdi-plus' }}</v-icon>
          {{ editIndex >= 0 ? '编辑规则' : '添加规则' }}
          <v-spacer />
          <v-switch v-model="editRule.enabled" label="启用" color="primary" density="compact" hide-details />
        </v-card-title>
        <v-divider />
        <v-card-text>
          <v-row dense>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="editRule.name" label="规则名称" placeholder="如：WOS 礼包码"
                density="compact" variant="outlined" prepend-inner-icon="mdi-tag"
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="editRule.quiet_hours" label="免打扰时段（可选）" placeholder="23:00-08:00，留空不启用"
                density="compact" variant="outlined" prepend-inner-icon="mdi-sleep"
                hint="时段内消息暂存，结束后汇总推送" persistent-hint
              />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12">
              <v-select
                v-model="editRule.channels" label="监听频道" :items="channelOptions"
                item-title="title" item-value="value"
                multiple chips closable-chips clearable
                density="compact" variant="outlined" prepend-inner-icon="mdi-pound"
                :loading="loadingChannels"
                no-data-text="暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
              />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12">
              <v-text-field
                v-model="manualChannel" label="手动添加频道 ID（可选）"
                placeholder="下拉列表没有的频道（如线程/论坛帖子）填 ID 后点 + 添加"
                density="compact" variant="outlined" prepend-inner-icon="mdi-pound-box"
                append-inner-icon="mdi-plus-circle" hide-details
                @click:append-inner="addManualChannel"
                @keyup.enter="addManualChannel"
              />
            </v-col>
          </v-row>
          <v-divider class="my-3" />
          <div class="text-subtitle-2 mb-2">
            <v-icon size="small" class="mr-1">mdi-arrow-decision</v-icon>
            投递去向（两种可同时用，至少选一种）
          </div>
          <v-row dense>
            <v-col cols="12" md="4">
              <v-switch
                v-model="editRule.notify_enabled" label="推送到通知渠道"
                color="primary" density="compact" hide-details
              />
            </v-col>
            <v-col cols="12" md="8">
              <v-select
                v-model="editRule.notify_channels" label="通知渠道" :items="notifierOptions"
                item-title="title" item-value="value"
                multiple chips closable-chips clearable
                :disabled="!editRule.notify_enabled"
                density="compact" variant="outlined" prepend-inner-icon="mdi-bell-ring"
                hint="留空 = 发送到全部启用的通知渠道" persistent-hint
              />
            </v-col>
          </v-row>
          <v-row dense class="mt-2">
            <v-col cols="12">
              <v-select
                v-model="editRule.forward_channels" label="转发到 Discord 频道（频道 → 频道）"
                :items="channelOptions" item-title="title" item-value="value"
                multiple chips closable-chips clearable
                density="compact" variant="outlined" prepend-inner-icon="mdi-forum"
                :loading="loadingChannels"
                hint="Bot 需要在目标频道有「发送消息」权限；留空则不转发到 Discord"
                persistent-hint
                no-data-text="暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
              />
            </v-col>
          </v-row>
          <v-row dense class="mt-2">
            <v-col cols="12">
              <v-text-field
                v-model="manualForward" label="手动添加转发目标频道 ID（可选）"
                placeholder="下拉列表没有的频道（如线程/论坛帖子）填 ID 后点 + 添加"
                density="compact" variant="outlined" prepend-inner-icon="mdi-forum-plus"
                append-inner-icon="mdi-plus-circle" hide-details
                @click:append-inner="addManualForward"
                @keyup.enter="addManualForward"
              />
            </v-col>
          </v-row>
          <v-alert
            v-if="editRule.forward_channels.length" type="info" variant="tonal"
            density="compact" class="mt-2 text-caption"
          >
            转发到 Discord 时会自动屏蔽 @everyone / 身份组提及，并跳过 Bot 自己发的消息防止死循环。
          </v-alert>
          <v-divider class="my-3" />
          <v-row dense>
            <v-col cols="6" md="3">
              <v-switch
                v-model="editRule.aggregate" label="消息聚合" color="info"
                density="compact" hide-details
                title="多条新消息合并成一条通知；想让每条码单独一条就关掉"
              />
            </v-col>
            <v-col cols="6" md="3">
              <v-switch
                v-model="editRule.forward_image" label="图片转发" color="info"
                density="compact" hide-details
              />
            </v-col>
            <v-col cols="6" md="3">
              <v-switch
                v-model="editRule.jump_link" label="跳转链接" color="info"
                density="compact" hide-details
                title="通知末尾的「点击查看：…」，关掉就不再附带"
              />
            </v-col>
            <v-col cols="6" md="3">
              <v-switch
                v-model="editRule.dedup" label="重复检测" color="info"
                density="compact" hide-details
                title="内容与近 7 天内已转发过的相同就不再发"
              />
            </v-col>
          </v-row>
          <div class="text-caption text-medium-emphasis mb-2">
            跳转链接 = 通知末尾的「点击查看：…」；重复检测 = 内容与近 7 天已转发的相同则跳过（有提取正则时按提取内容判定）
          </div>

          <v-expansion-panels variant="accordion" class="mt-2">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="small" class="mr-2">mdi-filter</v-icon>
                过滤规则（可选，留空全部转发）
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-row dense>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.keywords" label="关键词（白名单）"
                      placeholder="含任一关键词才转发，逗号或 | 分隔"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text-search"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.blocked_keywords" label="屏蔽词（黑名单）"
                      placeholder="含任一屏蔽词不转发"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text-box-remove"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.author_include" label="只转发这些作者"
                      placeholder="用户名精确匹配，不分大小写"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-account-check"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.author_exclude" label="屏蔽这些作者"
                      placeholder="用户名精确匹配，不分大小写"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-account-cancel"
                    />
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="small" class="mr-2">mdi-tune</v-icon>
                高级选项（可选，默认即可）
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-row dense>
                  <v-col cols="12">
                    <v-text-field
                      v-model="editRule.code_regex" label="内容提取正则（如礼包码）"
                      placeholder="留空不提取；可点右侧「示例」直接填入"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-regex"
                      hint="命中内容在通知中单独列出，对应模板变量 {codes}" persistent-hint
                    >
                      <template #append>
                        <v-menu location="bottom end">
                          <template #activator="{ props: menuProps }">
                            <v-btn
                              v-bind="menuProps" size="small" variant="tonal" color="info"
                              prepend-icon="mdi-lightbulb-on-outline"
                            >
                              示例
                            </v-btn>
                          </template>
                          <v-list density="compact" max-width="420">
                            <v-list-item
                              v-for="preset in regexPresets" :key="preset.title"
                              @click="applyPreset(preset)"
                            >
                              <v-list-item-title>{{ preset.title }}</v-list-item-title>
                              <v-list-item-subtitle class="text-wrap">
                                {{ preset.desc }}
                              </v-list-item-subtitle>
                            </v-list-item>
                            <v-list-item v-if="!regexPresets.length">
                              <v-list-item-title>示例加载中…</v-list-item-title>
                            </v-list-item>
                          </v-list>
                        </v-menu>
                      </template>
                    </v-text-field>
                  </v-col>
                  <v-col v-if="editRule.forward_channels.length" cols="12">
                    <v-textarea
                      v-model="editRule.discord_template" label="Discord 转发模板" rows="3"
                      placeholder="**{channel}** · {author} · {time}&#10;{content}&#10;🎁 {codes}&#10;🔗 {link}"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-forum"
                      hint="转发到 Discord 频道时用的正文，支持 Markdown，上限 2000 字；留空用默认模板"
                      persistent-hint
                    />
                  </v-col>
                  <v-col cols="12" md="5">
                    <v-text-field
                      v-model="editRule.title_template" label="标题模板"
                      placeholder="【Discord | {channel}】"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-format-title"
                    />
                  </v-col>
                  <v-col cols="12" md="7">
                    <v-textarea
                      v-model="editRule.text_template" label="内容模板" rows="3"
                      placeholder="{content}\n\n🎁 提取内容：{codes}\n\n👤 {author}  🕐 {time}"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text"
                      hint="变量：{channel} {author} {content} {codes} {time} {count} {link}；{codes}/{link} 为空时所在行自动隐藏" persistent-hint
                    />
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-card-text>
        <v-divider />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">取消</v-btn>
          <v-btn color="primary" @click="confirmRule">确定</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 删除确认弹窗 -->
    <v-dialog v-model="deleteDialog" max-width="360">
      <v-card>
        <v-card-title>删除规则</v-card-title>
        <v-card-text>
          确定删除规则「{{ deleteIndex >= 0 && config.rules[deleteIndex] ? config.rules[deleteIndex].name || '未命名规则' : '' }}」吗？
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">取消</v-btn>
          <v-btn color="error" @click="confirmDelete">删除</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.rule-card {
  height: 100%;
}
</style>
