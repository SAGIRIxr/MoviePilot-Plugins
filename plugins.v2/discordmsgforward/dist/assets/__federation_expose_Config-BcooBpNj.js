import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,withModifiers:_withModifiers,createElementVNode:_createElementVNode,withKeys:_withKeys,mergeProps:_mergeProps} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "mb-1" };
const _hoisted_3 = { class: "text-caption mb-1 text-truncate" };
const _hoisted_4 = { key: 1 };
const _hoisted_5 = {
  key: 0,
  class: "text-caption text-truncate"
};
const _hoisted_6 = { class: "d-flex" };
const _hoisted_7 = { class: "text-subtitle-2 mb-2" };

const {ref,reactive,computed,onMounted} = await importShared('vue');


const PLUGIN_ID = 'DiscordMsgForward';

const DOCS_URL =
  'https://github.com/SAGIRIxr/MoviePilot-Plugins/blob/main/plugins.v2/discordmsgforward/README.md';


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

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
});

const channelOptions = ref([]);
const notifierOptions = ref([]);
const msgtypeOptions = ref([]);
const regexPresets = ref([]);
const loadingChannels = ref(false);
const showToken = ref(false);
const message = ref('');
const messageType = ref('info');

// 规则编辑弹窗
const dialog = ref(false);
const editIndex = ref(-1);
const editRule = ref(defaultRule());

// 删除确认
const deleteDialog = ref(false);
const deleteIndex = ref(-1);

// 手动添加频道 ID
const manualChannel = ref('');
const manualForward = ref('');

function addManualId(source, field) {
  const cid = source.value.trim();
  if (!/^\d{5,}$/.test(cid)) {
    showMessage('频道 ID 应为纯数字', 'error');
    return
  }
  if (!editRule.value[field].includes(cid)) {
    editRule.value[field].push(cid);
  }
  source.value = '';
}

function addManualChannel() {
  addManualId(manualChannel, 'channels');
}

function addManualForward() {
  addManualId(manualForward, 'forward_channels');
}

function applyPreset(preset) {
  editRule.value.code_regex = preset.value;
  showMessage(`已填入「${preset.title}」正则`, 'success');
}

const channelNameMap = computed(() => {
  const map = {};
  channelOptions.value.forEach(o => { map[o.value] = o.title; });
  return map
});

function channelName(cid) {
  return channelNameMap.value[cid] || cid
}

function showMessage(text, type = 'info') {
  message.value = text;
  messageType.value = type;
  setTimeout(() => { message.value = ''; }, 4000);
}

async function loadOptions() {
  try {
    const [notifiers, msgtypes, presets] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/notifiers`),
      props.api.get(`plugin/${PLUGIN_ID}/msgtypes`),
      props.api.get(`plugin/${PLUGIN_ID}/regex_presets`),
    ]);
    notifierOptions.value = notifiers?.options || [];
    msgtypeOptions.value = msgtypes?.options || [];
    regexPresets.value = presets?.options || [];
  } catch (e) {
    console.error('加载选项失败', e);
  }
}

async function loadChannels(refresh = false) {
  loadingChannels.value = true;
  try {
    const res = await props.api.get(`plugin/${PLUGIN_ID}/channels`, { params: { refresh } });
    channelOptions.value = res?.options || [];
    if (refresh) {
      showMessage(`已刷新，共 ${channelOptions.value.length} 个频道`, 'success');
    }
  } catch (e) {
    console.error('加载频道失败', e);
    if (refresh) showMessage('刷新频道列表失败，请检查 Token 和代理', 'error');
  } finally {
    loadingChannels.value = false;
  }
}

function addRule() {
  editIndex.value = -1;
  editRule.value = defaultRule();
  dialog.value = true;
}

function openRule(index) {
  editIndex.value = index;
  editRule.value = JSON.parse(JSON.stringify(config.rules[index]));
  dialog.value = true;
}

function confirmRule() {
  if (!editRule.value.name) {
    editRule.value.name = `规则 ${config.rules.length + 1}`;
  }
  if (!editRule.value.notify_enabled && !editRule.value.forward_channels.length) {
    showMessage('请至少选择一个去向：推送到通知渠道，或转发到 Discord 频道', 'error');
    return
  }
  if (editIndex.value >= 0) {
    config.rules.splice(editIndex.value, 1, JSON.parse(JSON.stringify(editRule.value)));
  } else {
    config.rules.push(JSON.parse(JSON.stringify(editRule.value)));
  }
  dialog.value = false;
}

function askDelete(index) {
  deleteIndex.value = index;
  deleteDialog.value = true;
}

function confirmDelete() {
  if (deleteIndex.value >= 0) {
    config.rules.splice(deleteIndex.value, 1);
  }
  deleteDialog.value = false;
  deleteIndex.value = -1;
}

function ruleTargetSummary(rule) {
  const parts = [];
  if (rule.notify_enabled) {
    parts.push(rule.notify_channels.length ? rule.notify_channels.join('、') : '全部通知渠道');
  }
  if (rule.forward_channels?.length) {
    parts.push('Discord: ' + rule.forward_channels.map(channelName).join('、'));
  }
  return parts.length ? parts.join('　+　') : '未选去向'
}

function ruleFilterSummary(rule) {
  const parts = [];
  if (rule.keywords) parts.push(`关键词:${rule.keywords}`);
  if (rule.blocked_keywords) parts.push(`屏蔽:${rule.blocked_keywords}`);
  if (rule.author_include) parts.push(`作者:${rule.author_include}`);
  if (rule.author_exclude) parts.push(`排除作者:${rule.author_exclude}`);
  if (rule.code_regex) parts.push('提取正则');
  if (rule.dedup) parts.push('去重');
  if (rule.jump_link === false) parts.push('无跳转链接');
  return parts.join('　')
}

function saveConfig() {
  if (!config.token) {
    showMessage('请填写 Bot Token', 'error');
    return
  }
  emit('save', JSON.parse(JSON.stringify(config)));
}

onMounted(() => {
  loadOptions();
  loadChannels(false);
});

return (_ctx, _cache) => {
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_list_item_title = _resolveComponent("v-list-item-title");
  const _component_v_list_item_subtitle = _resolveComponent("v-list-item-subtitle");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_list = _resolveComponent("v-list");
  const _component_v_menu = _resolveComponent("v-menu");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (message.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: messageType.value,
          variant: "tonal",
          density: "compact",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createVNode(_component_v_card, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "info",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                _createTextVNode("mdi-cog", -1)
              ]))]),
              _: 1
            }),
            _cache[38] || (_cache[38] = _createTextVNode(" 全局设置 ", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_row, { dense: "" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.enabled,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
                      label: "启用插件",
                      color: "primary",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.use_proxy,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.use_proxy) = $event)),
                      label: "使用系统代理",
                      color: "warning",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.fail_alert,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.fail_alert) = $event)),
                      label: "失败告警",
                      color: "error",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.interval,
                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.interval) = $event)),
                      modelModifiers: { number: true },
                      label: "轮询间隔(分钟)",
                      type: "number",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-timer-outline",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_row, {
              dense: "",
              class: "mt-2"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "6"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.token,
                      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.token) = $event)),
                      label: "Bot Token",
                      type: showToken.value ? 'text' : 'password',
                      "append-inner-icon": showToken.value ? 'mdi-eye-off' : 'mdi-eye',
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-key",
                      hint: "保存后自动拉取 Bot 可见频道列表",
                      "persistent-hint": "",
                      autocomplete: "new-password",
                      "onClick:appendInner": _cache[5] || (_cache[5] = $event => (showToken.value = !showToken.value))
                    }, null, 8, ["modelValue", "type", "append-inner-icon"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_select, {
                      modelValue: config.msgtype,
                      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.msgtype) = $event)),
                      label: "通知类型",
                      items: msgtypeOptions.value,
                      "item-title": "title",
                      "item-value": "value",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-bell-outline",
                      hint: "所选通知渠道需开启该类型开关",
                      "persistent-hint": ""
                    }, null, 8, ["modelValue", "items"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.history_days,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.history_days) = $event)),
                      modelModifiers: { number: true },
                      label: "历史保留天数",
                      type: "number",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-history",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_v_card, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "info",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[39] || (_cache[39] = [
                _createTextVNode("mdi-swap-horizontal", -1)
              ]))]),
              _: 1
            }),
            _cache[42] || (_cache[42] = _createTextVNode(" 转发规则 ", -1)),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              color: "info",
              class: "mr-2",
              loading: loadingChannels.value,
              "prepend-icon": "mdi-refresh",
              onClick: _cache[8] || (_cache[8] = $event => (loadChannels(true)))
            }, {
              default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                _createTextVNode(" 刷新频道列表 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              size: "small",
              color: "primary",
              "prepend-icon": "mdi-plus",
              onClick: addRule
            }, {
              default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                _createTextVNode(" 添加规则 ", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            (!config.rules.length)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[43] || (_cache[43] = [
                    _createTextVNode(" 还没有转发规则，点击右上角「添加规则」创建第一条：选择监听频道和转发渠道即可。 ", -1)
                  ]))]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_v_row, {
                  key: 1,
                  dense: ""
                }, {
                  default: _withCtx(() => [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.rules, (rule, index) => {
                      return (_openBlock(), _createBlock(_component_v_col, {
                        key: rule.id,
                        cols: "12",
                        md: "6",
                        lg: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card, {
                            variant: "tonal",
                            color: rule.enabled ? 'primary' : undefined,
                            class: "rule-card"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_card_item, null, {
                                prepend: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    color: rule.enabled ? 'primary' : 'grey'
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(rule.enabled ? 'mdi-send-circle' : 'mdi-send-lock'), 1)
                                    ]),
                                    _: 2
                                  }, 1032, ["color"])
                                ]),
                                append: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: rule.enabled,
                                    "onUpdate:modelValue": $event => ((rule.enabled) = $event),
                                    color: "primary",
                                    density: "compact",
                                    "hide-details": "",
                                    onClick: _cache[9] || (_cache[9] = _withModifiers(() => {}, ["stop"]))
                                  }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                ]),
                                default: _withCtx(() => [
                                  _createVNode(_component_v_card_title, { class: "text-subtitle-1" }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(rule.name || '未命名规则'), 1)
                                    ]),
                                    _: 2
                                  }, 1024)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_card_text, { class: "pt-0" }, {
                                default: _withCtx(() => [
                                  _createElementVNode("div", _hoisted_2, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rule.channels.slice(0, 3), (cid) => {
                                      return (_openBlock(), _createBlock(_component_v_chip, {
                                        key: cid,
                                        size: "x-small",
                                        variant: "outlined",
                                        class: "mr-1 mb-1"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(channelName(cid)), 1)
                                        ]),
                                        _: 2
                                      }, 1024))
                                    }), 128)),
                                    (rule.channels.length > 3)
                                      ? (_openBlock(), _createBlock(_component_v_chip, {
                                          key: 0,
                                          size: "x-small",
                                          variant: "text",
                                          class: "mb-1"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(" +" + _toDisplayString(rule.channels.length - 3), 1)
                                          ]),
                                          _: 2
                                        }, 1024))
                                      : _createCommentVNode("", true),
                                    (!rule.channels.length)
                                      ? (_openBlock(), _createBlock(_component_v_chip, {
                                          key: 1,
                                          size: "x-small",
                                          color: "warning",
                                          variant: "tonal",
                                          class: "mb-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                                            _createTextVNode(" 未选频道 ", -1)
                                          ]))]),
                                          _: 1
                                        }))
                                      : _createCommentVNode("", true)
                                  ]),
                                  _createElementVNode("div", _hoisted_3, [
                                    _createVNode(_component_v_icon, {
                                      size: "x-small",
                                      class: "mr-1"
                                    }, {
                                      default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
                                        _createTextVNode("mdi-send", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _createTextVNode(" " + _toDisplayString(ruleTargetSummary(rule)) + " ", 1),
                                    (rule.quiet_hours)
                                      ? (_openBlock(), _createBlock(_component_v_icon, {
                                          key: 0,
                                          size: "x-small",
                                          class: "ml-2 mr-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                                            _createTextVNode("mdi-sleep", -1)
                                          ]))]),
                                          _: 1
                                        }))
                                      : _createCommentVNode("", true),
                                    (rule.quiet_hours)
                                      ? (_openBlock(), _createElementBlock("span", _hoisted_4, _toDisplayString(rule.quiet_hours), 1))
                                      : _createCommentVNode("", true)
                                  ]),
                                  (ruleFilterSummary(rule))
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
                                        _createVNode(_component_v_icon, {
                                          size: "x-small",
                                          class: "mr-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                                            _createTextVNode("mdi-filter", -1)
                                          ]))]),
                                          _: 1
                                        }),
                                        _createTextVNode(" " + _toDisplayString(ruleFilterSummary(rule)), 1)
                                      ]))
                                    : _createCommentVNode("", true)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_card_actions, { class: "pt-0" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_spacer),
                                  _createVNode(_component_v_btn, {
                                    size: "small",
                                    variant: "text",
                                    "prepend-icon": "mdi-pencil",
                                    onClick: $event => (openRule(index))
                                  }, {
                                    default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                                      _createTextVNode(" 编辑 ", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["onClick"]),
                                  _createVNode(_component_v_btn, {
                                    size: "small",
                                    variant: "text",
                                    color: "error",
                                    "prepend-icon": "mdi-delete",
                                    onClick: $event => (askDelete(index))
                                  }, {
                                    default: _withCtx(() => [...(_cache[49] || (_cache[49] = [
                                      _createTextVNode(" 删除 ", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["onClick"])
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1032, ["color"])
                        ]),
                        _: 2
                      }, 1024))
                    }), 128))
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_6, [
      _createVNode(_component_v_btn, {
        variant: "text",
        color: "primary",
        "prepend-icon": "mdi-book-open-variant",
        href: DOCS_URL,
        target: "_blank",
        rel: "noopener noreferrer"
      }, {
        default: _withCtx(() => [...(_cache[50] || (_cache[50] = [
          _createTextVNode(" 使用说明 ", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        class: "mr-2",
        variant: "text",
        onClick: _cache[10] || (_cache[10] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
          _createTextVNode("详情页", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_btn, {
        class: "mr-2",
        variant: "text",
        onClick: _cache[11] || (_cache[11] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_btn, {
        color: "primary",
        "prepend-icon": "mdi-content-save",
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
          _createTextVNode("保存配置", -1)
        ]))]),
        _: 1
      })
    ]),
    _createVNode(_component_v_dialog, {
      modelValue: dialog.value,
      "onUpdate:modelValue": _cache[34] || (_cache[34] = $event => ((dialog).value = $event)),
      "max-width": "800",
      scrollable: ""
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  color: "info",
                  class: "mr-2"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(editIndex.value >= 0 ? 'mdi-pencil' : 'mdi-plus'), 1)
                  ]),
                  _: 1
                }),
                _createTextVNode(" " + _toDisplayString(editIndex.value >= 0 ? '编辑规则' : '添加规则') + " ", 1),
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_switch, {
                  modelValue: editRule.value.enabled,
                  "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((editRule.value.enabled) = $event)),
                  label: "启用",
                  color: "primary",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: editRule.value.name,
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((editRule.value.name) = $event)),
                          label: "规则名称",
                          placeholder: "如：WOS 礼包码",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-tag"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: editRule.value.quiet_hours,
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((editRule.value.quiet_hours) = $event)),
                          label: "免打扰时段（可选）",
                          placeholder: "23:00-08:00，留空不启用",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-sleep",
                          hint: "时段内消息暂存，结束后汇总推送",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_select, {
                          modelValue: editRule.value.channels,
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((editRule.value.channels) = $event)),
                          label: "监听频道",
                          items: channelOptions.value,
                          "item-title": "title",
                          "item-value": "value",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          clearable: "",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-pound",
                          loading: loadingChannels.value,
                          "no-data-text": "暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
                        }, null, 8, ["modelValue", "items", "loading"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: manualChannel.value,
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((manualChannel).value = $event)),
                          label: "手动添加频道 ID（可选）",
                          placeholder: "下拉列表没有的频道（如线程/论坛帖子）填 ID 后点 + 添加",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-pound-box",
                          "append-inner-icon": "mdi-plus-circle",
                          "hide-details": "",
                          "onClick:appendInner": addManualChannel,
                          onKeyup: _withKeys(addManualChannel, ["enter"])
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_divider, { class: "my-3" }),
                _createElementVNode("div", _hoisted_7, [
                  _createVNode(_component_v_icon, {
                    size: "small",
                    class: "mr-1"
                  }, {
                    default: _withCtx(() => [...(_cache[54] || (_cache[54] = [
                      _createTextVNode("mdi-arrow-decision", -1)
                    ]))]),
                    _: 1
                  }),
                  _cache[55] || (_cache[55] = _createTextVNode(" 投递去向（两种可同时用，至少选一种） ", -1))
                ]),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "4"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.notify_enabled,
                          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((editRule.value.notify_enabled) = $event)),
                          label: "推送到通知渠道",
                          color: "primary",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "8"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_select, {
                          modelValue: editRule.value.notify_channels,
                          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((editRule.value.notify_channels) = $event)),
                          label: "通知渠道",
                          items: notifierOptions.value,
                          "item-title": "title",
                          "item-value": "value",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          clearable: "",
                          disabled: !editRule.value.notify_enabled,
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-bell-ring",
                          hint: "留空 = 发送到全部启用的通知渠道",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "items", "disabled"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, {
                  dense: "",
                  class: "mt-2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_select, {
                          modelValue: editRule.value.forward_channels,
                          "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((editRule.value.forward_channels) = $event)),
                          label: "转发到 Discord 频道（频道 → 频道）",
                          items: channelOptions.value,
                          "item-title": "title",
                          "item-value": "value",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          clearable: "",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-forum",
                          loading: loadingChannels.value,
                          hint: "Bot 需要在目标频道有「发送消息」权限；留空则不转发到 Discord",
                          "persistent-hint": "",
                          "no-data-text": "暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
                        }, null, 8, ["modelValue", "items", "loading"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, {
                  dense: "",
                  class: "mt-2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: manualForward.value,
                          "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((manualForward).value = $event)),
                          label: "手动添加转发目标频道 ID（可选）",
                          placeholder: "下拉列表没有的频道（如线程/论坛帖子）填 ID 后点 + 添加",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-forum-plus",
                          "append-inner-icon": "mdi-plus-circle",
                          "hide-details": "",
                          "onClick:appendInner": addManualForward,
                          onKeyup: _withKeys(addManualForward, ["enter"])
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                (editRule.value.forward_channels.length)
                  ? (_openBlock(), _createBlock(_component_v_alert, {
                      key: 0,
                      type: "info",
                      variant: "tonal",
                      density: "compact",
                      class: "mt-2 text-caption"
                    }, {
                      default: _withCtx(() => [...(_cache[56] || (_cache[56] = [
                        _createTextVNode(" 转发到 Discord 时会自动屏蔽 @everyone / 身份组提及，并跳过 Bot 自己发的消息防止死循环。 ", -1)
                      ]))]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                _createVNode(_component_v_divider, { class: "my-3" }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.aggregate,
                          "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((editRule.value.aggregate) = $event)),
                          label: "消息聚合",
                          color: "info",
                          density: "compact",
                          "hide-details": "",
                          title: "多条新消息合并成一条通知；想让每条码单独一条就关掉"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.forward_image,
                          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((editRule.value.forward_image) = $event)),
                          label: "图片转发",
                          color: "info",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.jump_link,
                          "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((editRule.value.jump_link) = $event)),
                          label: "跳转链接",
                          color: "info",
                          density: "compact",
                          "hide-details": "",
                          title: "通知末尾的「点击查看：…」，关掉就不再附带"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.dedup,
                          "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((editRule.value.dedup) = $event)),
                          label: "重复检测",
                          color: "info",
                          density: "compact",
                          "hide-details": "",
                          title: "内容与近 7 天内已转发过的相同就不再发"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _cache[63] || (_cache[63] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, " 跳转链接 = 通知末尾的「点击查看：…」；重复检测 = 内容与近 7 天已转发的相同则跳过（有提取正则时按提取内容判定） ", -1)),
                _createVNode(_component_v_expansion_panels, {
                  variant: "accordion",
                  class: "mt-2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_expansion_panel, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_expansion_panel_title, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, {
                              size: "small",
                              class: "mr-2"
                            }, {
                              default: _withCtx(() => [...(_cache[57] || (_cache[57] = [
                                _createTextVNode("mdi-filter", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[58] || (_cache[58] = _createTextVNode(" 过滤规则（可选，留空全部转发） ", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_expansion_panel_text, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_row, { dense: "" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.keywords,
                                      "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((editRule.value.keywords) = $event)),
                                      label: "关键词（白名单）",
                                      placeholder: "含任一关键词才转发，逗号或 | 分隔",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text-search"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.blocked_keywords,
                                      "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((editRule.value.blocked_keywords) = $event)),
                                      label: "屏蔽词（黑名单）",
                                      placeholder: "含任一屏蔽词不转发",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text-box-remove"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.author_include,
                                      "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((editRule.value.author_include) = $event)),
                                      label: "只转发这些作者",
                                      placeholder: "用户名精确匹配，不分大小写",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-account-check"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.author_exclude,
                                      "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => ((editRule.value.author_exclude) = $event)),
                                      label: "屏蔽这些作者",
                                      placeholder: "用户名精确匹配，不分大小写",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-account-cancel"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_expansion_panel, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_expansion_panel_title, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, {
                              size: "small",
                              class: "mr-2"
                            }, {
                              default: _withCtx(() => [...(_cache[59] || (_cache[59] = [
                                _createTextVNode("mdi-tune", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[60] || (_cache[60] = _createTextVNode(" 高级选项（可选，默认即可） ", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_expansion_panel_text, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_row, { dense: "" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_col, { cols: "12" }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.code_regex,
                                      "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((editRule.value.code_regex) = $event)),
                                      label: "内容提取正则（如礼包码）",
                                      placeholder: "留空不提取；可点右侧「示例」直接填入",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-regex",
                                      hint: "命中内容在通知中单独列出，对应模板变量 {codes}",
                                      "persistent-hint": ""
                                    }, {
                                      append: _withCtx(() => [
                                        _createVNode(_component_v_menu, { location: "bottom end" }, {
                                          activator: _withCtx(({ props: menuProps }) => [
                                            _createVNode(_component_v_btn, _mergeProps(menuProps, {
                                              size: "small",
                                              variant: "tonal",
                                              color: "info",
                                              "prepend-icon": "mdi-lightbulb-on-outline"
                                            }), {
                                              default: _withCtx(() => [...(_cache[61] || (_cache[61] = [
                                                _createTextVNode(" 示例 ", -1)
                                              ]))]),
                                              _: 1
                                            }, 16)
                                          ]),
                                          default: _withCtx(() => [
                                            _createVNode(_component_v_list, {
                                              density: "compact",
                                              "max-width": "420"
                                            }, {
                                              default: _withCtx(() => [
                                                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(regexPresets.value, (preset) => {
                                                  return (_openBlock(), _createBlock(_component_v_list_item, {
                                                    key: preset.title,
                                                    onClick: $event => (applyPreset(preset))
                                                  }, {
                                                    default: _withCtx(() => [
                                                      _createVNode(_component_v_list_item_title, null, {
                                                        default: _withCtx(() => [
                                                          _createTextVNode(_toDisplayString(preset.title), 1)
                                                        ]),
                                                        _: 2
                                                      }, 1024),
                                                      _createVNode(_component_v_list_item_subtitle, { class: "text-wrap" }, {
                                                        default: _withCtx(() => [
                                                          _createTextVNode(_toDisplayString(preset.desc), 1)
                                                        ]),
                                                        _: 2
                                                      }, 1024)
                                                    ]),
                                                    _: 2
                                                  }, 1032, ["onClick"]))
                                                }), 128)),
                                                (!regexPresets.value.length)
                                                  ? (_openBlock(), _createBlock(_component_v_list_item, { key: 0 }, {
                                                      default: _withCtx(() => [
                                                        _createVNode(_component_v_list_item_title, null, {
                                                          default: _withCtx(() => [...(_cache[62] || (_cache[62] = [
                                                            _createTextVNode("示例加载中…", -1)
                                                          ]))]),
                                                          _: 1
                                                        })
                                                      ]),
                                                      _: 1
                                                    }))
                                                  : _createCommentVNode("", true)
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ]),
                                      _: 1
                                    }, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                (editRule.value.forward_channels.length)
                                  ? (_openBlock(), _createBlock(_component_v_col, {
                                      key: 0,
                                      cols: "12"
                                    }, {
                                      default: _withCtx(() => [
                                        _createVNode(_component_v_textarea, {
                                          modelValue: editRule.value.discord_template,
                                          "onUpdate:modelValue": _cache[30] || (_cache[30] = $event => ((editRule.value.discord_template) = $event)),
                                          label: "Discord 转发模板",
                                          rows: "3",
                                          placeholder: "**{channel}** · {author} · {time}\n{content}\n🎁 {codes}\n🔗 {link}",
                                          density: "compact",
                                          variant: "outlined",
                                          "prepend-inner-icon": "mdi-forum",
                                          hint: "转发到 Discord 频道时用的正文，支持 Markdown，上限 2000 字；留空用默认模板",
                                          "persistent-hint": ""
                                        }, null, 8, ["modelValue"])
                                      ]),
                                      _: 1
                                    }))
                                  : _createCommentVNode("", true),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "5"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.title_template,
                                      "onUpdate:modelValue": _cache[31] || (_cache[31] = $event => ((editRule.value.title_template) = $event)),
                                      label: "标题模板",
                                      placeholder: "【Discord | {channel}】",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-format-title"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "7"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_textarea, {
                                      modelValue: editRule.value.text_template,
                                      "onUpdate:modelValue": _cache[32] || (_cache[32] = $event => ((editRule.value.text_template) = $event)),
                                      label: "内容模板",
                                      rows: "3",
                                      placeholder: "{content}\\n\\n🎁 提取内容：{codes}\\n\\n👤 {author}  🕐 {time}",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text",
                                      hint: "变量：{channel} {author} {content} {codes} {time} {count} {link}；{codes}/{link} 为空时所在行自动隐藏",
                                      "persistent-hint": ""
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  onClick: _cache[33] || (_cache[33] = $event => (dialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[64] || (_cache[64] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  onClick: confirmRule
                }, {
                  default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
                    _createTextVNode("确定", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_v_dialog, {
      modelValue: deleteDialog.value,
      "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((deleteDialog).value = $event)),
      "max-width": "360"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
                _createTextVNode("删除规则", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createTextVNode(" 确定删除规则「" + _toDisplayString(deleteIndex.value >= 0 && config.rules[deleteIndex.value] ? config.rules[deleteIndex.value].name || '未命名规则' : '') + "」吗？ ", 1)
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  onClick: _cache[35] || (_cache[35] = $event => (deleteDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[67] || (_cache[67] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "error",
                  onClick: confirmDelete
                }, {
                  default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                    _createTextVNode("删除", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c27a03d9"]]);

export { Config as default };
